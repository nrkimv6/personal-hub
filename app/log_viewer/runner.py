"""
runner.py — plan-runner Redis 조회

logs.ps1의 Get-ActiveRunners / Get-RunnerDisplayName / Get-RunnerFileId 로직을
Python으로 이식한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunnerInfo:
    runner_id: str
    log_path: str | None
    stream_path: str | None
    plan_file: str | None
    pid: str | None
    short_id: str = field(init=False)
    display_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.short_id = get_runner_file_id(
            Path(self.log_path).name if self.log_path else ""
        )
        if not self.short_id and self.stream_path:
            self.short_id = get_runner_stream_file_id(Path(self.stream_path).name)
        self.display_name = get_runner_display_name(self.plan_file or "", fallback=self.runner_id)


def get_runner_display_name(plan_file: str, fallback: str = "(unknown)") -> str:
    """
    plan_file 경로에서 표시 이름을 추출한다.

    예: "D:/.../ 2026-02-25_smart-push-auto-rebase.md" → "smart-push"

    규칙 (logs.ps1 기준):
      1. 파일명에서 YYYY-MM-DD_ 접두사 제거
      2. .md 확장자 제거
      3. 첫 번째 '-' 구분 단어 최대 2개 반환 (단어가 1개면 그대로)
         예: smart-push-auto-rebase → "smart-push"

    plan_file이 비어있으면 fallback을 반환한다.
    """
    if not plan_file:
        return fallback

    name = Path(plan_file).stem  # 확장자 제거
    # YYYY-MM-DD_ 접두사 제거
    name = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", name)
    # fix- 접두사 제거 (예: fix-smart-push → smart-push)
    name = re.sub(r"^fix-", "", name)

    parts = name.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else name


def get_runner_file_id(filename: str) -> str:
    """
    plan-runner 로그 파일명에서 짧은 식별자를 추출한다.

    TC runner: plan-runner-t-{name}-YYYYMMDD-HHmmss.log → "t-{name}"
    신규 형식: plan-runner-{8자hex}-YYYYMMDD-HHmmss.log → runner_id (8자 hex)
    구버전 형식: plan-runner-YYYYMMDD-HHmmss.log → HHmmss (6자)
    매칭 없음: 빈 문자열 반환
    """
    # TC runner 형식 (먼저 매칭 — 8자 hex 패턴보다 우선)
    m = re.search(r"plan-runner-(t-.+?)-\d{8}-\d{6}", filename)
    if m:
        return m.group(1)
    # 신규 형식
    m = re.search(r"plan-runner-([0-9a-f]{8})-\d{8}-\d{6}", filename)
    if m:
        return m.group(1)
    # 구버전 형식
    m = re.search(r"plan-runner-\d{8}-(\d{6})", filename)
    if m:
        return m.group(1)
    return ""


def get_runner_stream_file_id(filename: str) -> str:
    """plan-runner stream 로그 파일명에서 runner_id를 추출한다."""
    m = re.search(r"plan-runner-stream-(.+?)-\d{8}(?:[-_]\d{6})?\.log", filename)
    if m:
        return m.group(1)
    return ""


def get_active_runners(redis_client: Any = None) -> list[RunnerInfo]:
    """
    Redis에서 활성 plan-runner 목록을 조회한다.

    Redis 키 구조 (logs.ps1 기준):
      - plan-runner:active_runners  — set, 활성 runner_id 집합
      - plan-runner:runners:{rid}:log_file_path
      - plan-runner:runners:{rid}:stream_log_path
      - plan-runner:runners:{rid}:plan_file
      - plan-runner:runners:{rid}:pid

    Parameters
    ----------
    redis_client:
        redis.Redis 인스턴스. None이면 기본 설정(localhost:6379)으로 연결 시도.
        연결 실패 시 빈 리스트를 반환한다.

    Returns
    -------
    list[RunnerInfo] — 활성 runner 목록. Redis 미연결/오류 시 빈 리스트.
    """
    if redis_client is None:
        try:
            import redis  # type: ignore

            redis_client = redis.Redis(socket_timeout=2)
            redis_client.ping()
        except Exception:
            return []

    try:
        raw_ids = set(redis_client.smembers("plan-runner:active_runners") or set())
    except Exception:
        return []
    try:
        recent_ids = redis_client.zrevrange("plan-runner:recent_runners", 0, 49) or []
    except Exception:
        try:
            recent_ids = redis_client.zrange("plan-runner:recent_runners", 0, 49) or []
        except Exception:
            recent_ids = []

    def _get(key: str) -> str | None:
        try:
            val = redis_client.get(key)
            if val is None:
                return None
            return val.decode("utf-8") if isinstance(val, bytes) else str(val)
        except Exception:
            return None

    runners: list[RunnerInfo] = []
    seen: set[str] = set()
    for rid_b in recent_ids:
        rid = rid_b.decode("utf-8") if isinstance(rid_b, bytes) else str(rid_b)
        if _get(f"plan-runner:runners:{rid}:merge_status") == "approval_required":
            raw_ids.add(rid)

    for rid_b in raw_ids:
        rid = rid_b.decode("utf-8") if isinstance(rid_b, bytes) else str(rid_b)
        if rid in seen:
            continue
        seen.add(rid)
        prefix = f"plan-runner:runners:{rid}"
        runners.append(
            RunnerInfo(
                runner_id=rid,
                log_path=_get(f"{prefix}:log_file_path"),
                stream_path=_get(f"{prefix}:stream_log_path"),
                plan_file=_get(f"{prefix}:plan_file"),
                pid=_get(f"{prefix}:pid"),
            )
        )
    return runners
