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

from app.log_viewer.config import CLEANUP_FILTER_PATTERN, LogSource
from app.log_viewer.finder import find_latest_log
from app.log_viewer.runner import RunnerInfo, get_active_runners
from app.log_viewer.stale import is_stale


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


def _read_tail_lines(path: Path, n: int, encoding: str = "utf-8") -> list[str]:
    """파일 끝에서 n줄을 읽어 반환한다. n=0이거나 파일이 없으면 빈 리스트."""
    if n <= 0:
        return []
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            lines = f.readlines()
        result = [ln.rstrip("\n") for ln in lines if ln.rstrip("\n")]
        return result[-n:] if result else []
    except OSError:
        return []


# ---------------------------------------------------------------------------
# FileTailer — 단일 파일 tail
# ---------------------------------------------------------------------------


class FileTailer:
    """단일 파일을 tail한다.

    생성 시점의 파일 크기를 기억하고, 이후 추가된 줄만 반환한다.
    파일 rotation(삭제 후 재생성) 시 처음부터 읽기로 리셋한다.
    """

    def __init__(self, path: Path, encoding: str = "utf-8", initial_tail: int = 0) -> None:
        self._path = path
        self._encoding = encoding
        # 기존 내용 스킵 — 신규 줄만 읽기 (initial_tail > 0이어도 _pos는 파일 끝으로 설정)
        try:
            self._pos: int = path.stat().st_size
        except OSError:
            self._pos = 0
        # initial_tail > 0이면 파일 끝 N줄을 첫 read_new_lines 호출 시 반환
        self._initial_buffer: list[str] = (
            _read_tail_lines(path, initial_tail, encoding) if initial_tail > 0 else []
        )

    def read_new_lines(self) -> list[str]:
        """마지막 읽기 위치 이후의 새 줄을 반환한다.

        첫 호출 시 _initial_buffer에 내용이 있으면 먼저 반환하고 버퍼를 비운다.
        파일 미존재 또는 크기 축소(rotation) 시 _pos를 0으로 리셋하여
        새 파일을 처음부터 읽는다.
        """
        if self._initial_buffer:
            buf = self._initial_buffer
            self._initial_buffer = []
            return buf
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
        initial_tail: int = 0,
        replace: bool = False,
    ) -> None:
        """소스를 추가한다.

        replace=False(기본): 같은 name이 있으면 무시한다.
        replace=True: StaticSourceWatcher가 path 교체 시 사용 — 기존 항목을 새 FileTailer로 덮어쓴다.
        initial_tail > 0: FileTailer 생성 시 파일 끝 N줄을 첫 호출에 반환한다.
        """
        if name in self._sources and not replace:
            return
        self._sources[name] = _SourceEntry(
            name=name,
            tailer=FileTailer(path, initial_tail=initial_tail),
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


# ---------------------------------------------------------------------------
# StaticSourceWatcher — 정적 소스 주기적 재스캔
# ---------------------------------------------------------------------------


class StaticSourceWatcher:
    """정적 소스(config.LOG_SOURCES)를 주기적으로 재스캔하여 tailer에 등록/교체한다.

    부팅 직후 아직 존재하지 않는 로그 파일을 주기적으로 발견하고,
    find_latest_log가 어제 파일을 반환하던 상황도 오늘 파일로 교체한다.

    사용:
        watcher = StaticSourceWatcher(list(get_sources(admin)), dirs)
        while True:
            watcher.refresh(tailer)   # 10초 주기로 noop
            ...
    """

    _REFRESH_INTERVAL: float = 10.0

    def __init__(self, sources: list[LogSource], dirs: list[Path]) -> None:
        import os as _os
        self._sources = sources
        self._dirs = dirs
        # source.name → resolved path string (중복 등록 방지)
        self._known_paths: dict[str, str] = {}
        # 첫 호출 즉시 실행 보장
        self._last_refresh: float = -float("inf")
        # 테스트용: STATIC_WATCHER_INTERVAL 환경변수로 interval 오버라이드 가능
        _override = _os.environ.get("STATIC_WATCHER_INTERVAL")
        if _override:
            try:
                self._REFRESH_INTERVAL = float(_override)
            except ValueError:
                pass

    def refresh(self, tailer: MultiTailer) -> None:
        """정적 소스를 재스캔하고 신규/변경된 파일을 tailer에 등록한다.

        _REFRESH_INTERVAL 미경과 시 즉시 return.
        """
        now = time.monotonic()
        if now - self._last_refresh < self._REFRESH_INTERVAL:
            return
        self._last_refresh = now

        for src in self._sources:
            patterns = [f"{p}*" for p in src.patterns]
            path = find_latest_log(patterns, self._dirs)
            if path is None:
                continue
            # 오래된 파일(어제 파일 등)은 등록하지 않음 — 오늘 파일이 생길 때까지 대기
            if is_stale(path):
                continue

            resolved = str(path.resolve())
            prev = self._known_paths.get(src.name)

            if prev == resolved:
                # 동일 파일 → noop
                continue

            # 신규 또는 path 변경 → tailer에 등록/교체
            action = "교체" if prev is not None else "신규 감지"
            tailer.add_source(
                src.name,
                path,
                src.color,
                error_only=src.error_only,
                initial_tail=src.tail_lines,
                replace=True,
            )
            self._known_paths[src.name] = resolved
            print(
                f"[{src.name}] === {action}: {path.name} ===",
                flush=True,
            )
