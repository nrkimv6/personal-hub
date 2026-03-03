"""API 사망 추적 시스템 — 구조화된 JSON 로그 기록.

로그 파일: logs/death_log.json  (JSONL 형식, 한 줄에 JSON 1개)

이벤트 종류:
  start              — 프로세스 시작
  death              — 프로세스 종료 (원인 포함)
  crash_loop_detected — 크래시 루프 감지

사망 원인(cause):
  normal_shutdown    — 정상 종료 (self-restart, lifespan shutdown)
  signal             — 시그널 수신 (SIGTERM, SIGINT 등)
  python_exception   — 처리되지 않은 Python 예외
  external_kill      — 외부 TerminateProcess (exit code로 추정)
  system_reboot      — 시스템 재부팅 (이전 start 기록 부재)
  unknown            — 원인 불명
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 로그 파일 경로 (프로세스 시작 시간 기준으로 고정)
_LOG_PATH = Path("logs/death_log.json")
_PID = os.getpid()
_START_TIME: Optional[float] = None  # time.time() — 시작 시 기록

# 마지막 요청 경로 추적 (미들웨어에서 업데이트)
_last_request_path: Optional[str] = None


# ── 내부 유틸 ────────────────────────────────────────────────

def _ensure_log_dir() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _trim_log(keep: int = 500) -> None:
    """파일 줄 수가 keep 초과 시 앞쪽 줄 제거 (no-op if ≤ keep or file absent)."""
    try:
        if not _LOG_PATH.exists():
            return
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) <= keep:
            return
        _LOG_PATH.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _write_entry(entry: dict[str, Any]) -> None:
    """JSONL 형식으로 한 줄 기록 (예외 무시)."""
    try:
        _ensure_log_dir()
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _uptime_seconds() -> int:
    if _START_TIME is None:
        return 0
    return max(0, int(time.time() - _START_TIME))


# ── 공개 API ─────────────────────────────────────────────────

def set_last_request(path: str) -> None:
    """미들웨어에서 요청 경로를 업데이트합니다."""
    global _last_request_path
    _last_request_path = path


def record_start() -> None:
    """프로세스 시작 이벤트를 기록합니다."""
    global _START_TIME
    _trim_log()
    _START_TIME = time.time()
    _write_entry({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pid": _PID,
        "event": "start",
        "cause": None,
        "exit_code": None,
        "uptime_seconds": 0,
        "details": None,
        "last_request": None,
    })


def record_death(
    cause: str,
    exit_code: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    """프로세스 종료 이벤트를 기록합니다.

    Args:
        cause: 사망 원인 문자열
        exit_code: 종료 코드 (있는 경우)
        details: 추가 정보 (traceback, signal 번호 등)
    """
    _write_entry({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pid": _PID,
        "event": "death",
        "cause": cause,
        "exit_code": exit_code,
        "uptime_seconds": _uptime_seconds(),
        "details": details,
        "last_request": _last_request_path,
    })


def record_crash_loop(restart_count: int, window_minutes: int, first_error: Optional[str] = None) -> None:
    """크래시 루프 감지 이벤트를 기록합니다."""
    _write_entry({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "pid": _PID,
        "event": "crash_loop_detected",
        "cause": "crash_loop",
        "exit_code": None,
        "uptime_seconds": _uptime_seconds(),
        "details": f"{window_minutes}분 내 {restart_count}회 재시작. 첫 에러: {first_error}",
        "last_request": _last_request_path,
    })


# ── 로그 읽기 (API용) ────────────────────────────────────────

def read_recent_entries(limit: int = 50) -> list[dict[str, Any]]:
    """최근 N개 항목을 반환합니다 (최신 항목이 앞에 옴)."""
    try:
        if not _LOG_PATH.exists():
            return []
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= limit:
                break
        return entries
    except Exception:
        return []


def read_recent_deaths(
    window_minutes: int = 5,
    exclude_causes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """최근 N분 내 death 이벤트 목록을 반환합니다 (크래시 루프 감지용).

    Args:
        window_minutes: 탐색 윈도우 (분 단위).
        exclude_causes: 제외할 cause 값 목록. 해당 cause의 이벤트는 결과에서 제외된다.
            예: ``["normal_shutdown"]`` — 정상 종료는 크래시 카운트에서 제외.
            ``None``(기본값)이면 모든 death 이벤트를 반환한다 (하위 호환).
    """
    try:
        if not _LOG_PATH.exists():
            return []
        cutoff = datetime.now().timestamp() - window_minutes * 60
        deaths = []
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") != "death":
                continue
            if exclude_causes and entry.get("cause") in exclude_causes:
                continue
            try:
                ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                if ts >= cutoff:
                    deaths.append(entry)
            except Exception:
                continue
        return deaths
    except Exception:
        return []


def had_clean_shutdown(pid: int) -> bool:
    """해당 PID의 start 이벤트 이후 death 이벤트가 있었는지 확인합니다.

    True  → 이전 세션이 정상 종료됨
    False → 비정상 종료 (재부팅, 외부 kill 등) 의심
    """
    try:
        if not _LOG_PATH.exists():
            return True  # 기록 없음 → 첫 실행으로 간주
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
        found_start = False
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("pid") != pid:
                continue
            if entry.get("event") == "death":
                return True
            if entry.get("event") == "start":
                found_start = True
                break
        return not found_start  # start 없으면 첫 실행
    except Exception:
        return True
