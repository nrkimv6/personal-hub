"""
follower.py — Follow 모드 핵심 엔진

logs.ps1의 Start-LogTail / Start-CombinedLogTail 로직을 Python으로 이식한다.
- FileTailer: 단일 파일 tail (200ms polling)
- MultiTailer: 다중 소스 통합 tail
- RunnerWatcher: Redis runner 동적 추가/제거 (10초 주기, 30초 grace period)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.log_viewer.config import CLEANUP_FILTER_PATTERN
from app.log_viewer.runner import RunnerInfo, get_active_runners


# ---------------------------------------------------------------------------
# 레벨 / 에러 감지 패턴
# ---------------------------------------------------------------------------

_LEVEL_PATTERN = re.compile(r"(?i)\b(ERROR|CRITICAL|WARNING|WARN|INFO|DEBUG)\b")

# error_only 소스용 필터 패턴 (PS1 L1074 $errorOnlySources 필터 기반 + Python Traceback 추가)
_ERROR_PATTERN = re.compile(
    r"ERROR|CRITICAL|Exception|WARN|error|fail|ERR_|TypeError|ReferenceError|SyntaxError|Traceback"
)


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class LogLine:
    """단일 로그 줄 — 출력/필터 전달용 불변 컨테이너."""

    source: str
    text: str
    color: str
    level: Optional[str]


@dataclass
class _SourceEntry:
    """MultiTailer 내부용 소스 항목."""

    name: str
    tailer: "FileTailer"
    color: str
    error_only: bool


# ---------------------------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------------------------


def _detect_level(line: str) -> Optional[str]:
    """줄에서 로그 레벨 키워드를 감지한다.

    Returns:
        "ERROR" | "CRITICAL" | "WARNING" | "WARN" | "INFO" | "DEBUG" | None
    """
    m = _LEVEL_PATTERN.search(line)
    return m.group(1).upper() if m else None


def _is_error_line(line: str) -> bool:
    """error_only 소스 필터: 에러/경고 수준 줄인지 판단한다."""
    return bool(_ERROR_PATTERN.search(line))


def _apply_filters(
    line: str,
    error_only: bool,
    cleanup_pattern: Optional[str],
) -> bool:
    """필터 적용 — True면 출력, False면 필터됨.

    순서:
    1. error_only=True이고 에러 줄이 아니면 → False
    2. cleanup_pattern이 있고 매칭되지 않으면 → False
    3. 나머지 → True
    """
    if error_only and not _is_error_line(line):
        return False
    if cleanup_pattern is not None and not re.search(cleanup_pattern, line):
        return False
    return True


# ---------------------------------------------------------------------------
# FileTailer — 단일 파일 tail
# ---------------------------------------------------------------------------


class FileTailer:
    """단일 파일을 tail한다.

    생성 시점의 파일 크기를 기억하고, 이후 추가된 줄만 반환한다.
    파일 rotation(삭제 후 재생성) 시 처음부터 읽기로 리셋한다.
    """

    def __init__(self, path: Path, encoding: str = "utf-8") -> None:
        self._path = path
        self._encoding = encoding
        # 기존 내용 스킵 — 신규 줄만 읽기
        try:
            self._pos: int = path.stat().st_size
        except OSError:
            self._pos = 0

    def read_new_lines(self) -> list[str]:
        """마지막 읽기 위치 이후의 새 줄을 반환한다.

        파일 미존재 또는 크기 축소(rotation) 시 _pos를 0으로 리셋하여
        새 파일을 처음부터 읽는다.
        """
        try:
            current_size = self._path.stat().st_size
        except OSError:
            return []

        # rotation 감지: 파일 크기가 _pos보다 작아진 경우
        if current_size < self._pos:
            self._pos = 0

        if current_size == self._pos:
            return []

        try:
            with open(self._path, encoding=self._encoding, errors="replace") as f:
                f.seek(self._pos)
                raw = f.read()
                self._pos = f.tell()
        except OSError:
            return []

        # 줄 단위로 분리하되 빈 줄(trailing newline)은 제외
        return [ln for ln in raw.splitlines() if ln]


# ---------------------------------------------------------------------------
# MultiTailer — 다중 소스 통합 tail
# ---------------------------------------------------------------------------


class MultiTailer:
    """다중 파일 소스를 동시에 tail한다.

    poll_once()를 200ms 간격 외부 루프에서 호출하면
    모든 소스의 새 줄을 LogLine 리스트로 반환한다.
    """

    def __init__(self, cleanup: bool = False) -> None:
        self._sources: dict[str, _SourceEntry] = {}
        self._cleanup_pattern: Optional[str] = CLEANUP_FILTER_PATTERN if cleanup else None

    def add_source(
        self,
        name: str,
        path: Path,
        color: str,
        error_only: bool = False,
    ) -> None:
        """소스를 추가한다. 이미 같은 name이 있으면 무시한다."""
        if name in self._sources:
            return
        self._sources[name] = _SourceEntry(
            name=name,
            tailer=FileTailer(path),
            color=color,
            error_only=error_only,
        )

    def remove_source(self, name: str) -> None:
        """소스를 제거한다. 없으면 무시한다."""
        self._sources.pop(name, None)

    def poll_once(self) -> list[LogLine]:
        """모든 소스에서 새 줄을 수집하여 반환한다."""
        result: list[LogLine] = []
        for entry in list(self._sources.values()):
            for line in entry.tailer.read_new_lines():
                if _apply_filters(line, entry.error_only, self._cleanup_pattern):
                    result.append(
                        LogLine(
                            source=entry.name,
                            text=line,
                            color=entry.color,
                            level=_detect_level(line),
                        )
                    )
        return result


# ---------------------------------------------------------------------------
# RunnerWatcher — Redis runner 동적 관리
# ---------------------------------------------------------------------------


class RunnerWatcher:
    """Redis에서 active runner 목록을 주기적으로 갱신한다.

    - 10초 주기로 get_active_runners() 호출
    - 신규 runner → tailer에 add_source()
    - 부재 runner → 30초 grace period 후 tailer에서 remove_source()
    - grace 중 복귀 시 grace 취소 (PS1 L946-969 이식)

    time.monotonic() 사용으로 시스템 시계 변경에 내성이 있다.
    """

    _REFRESH_INTERVAL: float = 10.0
    _GRACE_PERIOD: float = 30.0

    def __init__(self) -> None:
        self._known_runners: set[str] = set()
        # runner_id → (short_id, stale_시작_시각)
        self._stale_tracker: dict[str, tuple[str, float]] = {}
        self._last_refresh: float = 0.0
        # runner_id → short_id 역매핑 (grace 만료 시 소스 이름 재구성에 필요)
        self._id_to_short: dict[str, str] = {}

    def refresh(self, tailer: MultiTailer) -> None:
        """runner 목록을 갱신하고 tailer를 동기화한다.

        10초 미경과 시 즉시 return.
        """
        now = time.monotonic()
        if now - self._last_refresh < self._REFRESH_INTERVAL:
            return
        self._last_refresh = now

        runners: list[RunnerInfo] = get_active_runners()
        current_ids = {r.runner_id for r in runners}
        runner_map = {r.runner_id: r for r in runners}

        # --- 신규 runner 추가 ---
        new_ids = current_ids - self._known_runners
        for rid in new_ids:
            r = runner_map[rid]
            self._id_to_short[rid] = r.short_id
            if r.log_path:
                tailer.add_source(f"PR:{r.short_id}", Path(r.log_path), "white")
            if r.stream_path:
                tailer.add_source(
                    f"PS:{r.short_id}", Path(r.stream_path), "bright_black"
                )
            self._known_runners.add(rid)
            # grace 상태에서 복귀한 경우 grace 취소
            self._stale_tracker.pop(rid, None)

        # --- grace 중 복귀 취소 (PS1 L966-969 이식) ---
        for rid in list(self._stale_tracker.keys()):
            if rid in current_ids:
                del self._stale_tracker[rid]

        # --- grace period 관리 ---
        stale_ids = self._known_runners - current_ids
        for sid in list(stale_ids):
            if sid not in self._stale_tracker:
                # grace 시작
                short_id = self._id_to_short.get(sid, sid)
                self._stale_tracker[sid] = (short_id, now)
            else:
                short_id, start_time = self._stale_tracker[sid]
                if now - start_time >= self._GRACE_PERIOD:
                    # grace 만료 → tailer에서 제거
                    tailer.remove_source(f"PR:{short_id}")
                    tailer.remove_source(f"PS:{short_id}")
                    self._known_runners.discard(sid)
                    del self._stale_tracker[sid]
                    self._id_to_short.pop(sid, None)
