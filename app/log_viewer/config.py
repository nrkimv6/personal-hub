"""
config.py — 로그 소스 설정 (패턴, 색상, tail 줄수)

logs.ps1의 $logConfig, $timestampedLogPatterns 를 Python 데이터 구조로 이식한다.
CLI/static 모드와 Follow 모드 모두에서 단일 진실의 원천(SSOT)으로 사용된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LogSource:
    """단일 로그 소스 설정."""

    # 표시 이름 (예: "API", "WORKER")
    name: str

    # 파일 탐색 패턴 목록 (glob prefix, 예: ["stdout_api_", "api_"])
    patterns: list[str]

    # rich/colorama 색상 이름 (예: "cyan", "magenta")
    color: str

    # static 모드에서 출력할 초기 tail 줄수
    tail_lines: int = 5

    # Admin 전용 여부: True이면 --admin 없이는 숨김
    admin_only: bool = False

    # 로그 디렉토리 오버라이드 (None이면 기본 logs/ 또는 logs/admin/ 사용)
    log_dir: Optional[Path] = None

    # Follow 모드에서 error/warning 행만 표시할지 여부
    error_only: bool = False

    # stale 판정 대상 여부 (파일명 날짜 기반으로 이전 세션 파일 제외)
    check_stale: bool = False

    # Public-safe 표면에 노출 가능한지 여부.
    # API/worker/watchdog/runner 계열은 프로세스 진단이 섞일 수 있어 opt-in만 허용한다.
    public_safe: bool = False


# ---------------------------------------------------------------------------
# 기본 로그 소스 목록 (logs.ps1 $logConfig / $timestampedLogPatterns 대응)
# ---------------------------------------------------------------------------
# 색상명은 rich 라이브러리 기준 (bold/dim 등 조합 가능)
# logs.ps1 ConsoleColor → rich 대응:
#   Cyan       → "cyan"
#   Magenta    → "magenta"
#   Green      → "green"
#   DarkGray   → "bright_black"
#   DarkCyan   → "dark_cyan" (rich에서는 "cyan" dim 처리)
#   DarkBlue   → "blue"
#   DarkGreen  → "dark_green"
#   DarkYellow → "yellow"
#   White      → "white"
#   Blue       → "blue"

LOG_SOURCES: list[LogSource] = [
    LogSource(
        name="SERVICE",
        patterns=["service_runner_"],
        color="dark_cyan",
        tail_lines=3,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="TUNNEL",
        patterns=["cloudflared_err_", "cloudflared_err-", "cloudflared_"],
        color="bright_black",
        tail_lines=3,
        admin_only=False,
        check_stale=False,
        public_safe=True,
    ),
    LogSource(
        name="API",
        # stdout_api_*: 레거시(NSSM→service 전환), api_*: 현재
        # Admin 모드에서는 base logs/ 도 탐색 (finder에서 처리)
        patterns=["stdout_api_", "api_"],
        color="cyan",
        tail_lines=5,
        admin_only=False,
        check_stale=False,
    ),
    LogSource(
        name="WORKER",
        # WORKER 뷰는 구조화 본로그(worker_*)를 기준으로 본다.
        # stdout_unified_worker_*는 stdout 캡처용 보조 로그라 일부 워커 이벤트가 누락될 수 있다.
        patterns=["worker_", "unified_worker_"],
        color="magenta",
        tail_lines=5,
        admin_only=True,
        check_stale=True,
    ),
    LogSource(
        name="LLM",
        patterns=["llm_worker_"],
        color="blue",
        tail_lines=3,
        admin_only=True,
        check_stale=True,
    ),
    LogSource(
        name="VIDEO-DL",
        # stdout_video_download_worker_*: 레거시(Python 앱 자체 로깅으로 전환됨)
        patterns=["stdout_video_download_worker_", "video_download_worker_"],
        color="dark_green",
        tail_lines=5,
        admin_only=True,
        check_stale=True,
    ),
    LogSource(
        name="CRAWL",
        # stdout_crawl_*: 레거시(Python 앱 자체 로깅으로 전환됨)
        patterns=["stdout_crawl_", "crawl_worker_"],
        color="blue",
        tail_lines=5,
        admin_only=True,
        check_stale=True,
    ),
    LogSource(
        name="FRONTEND",
        patterns=["frontend_2"],
        color="green",
        tail_lines=3,
        admin_only=False,
        check_stale=True,
        error_only=True,  # Follow 모드에서 error/warning만 표시
        public_safe=True,
    ),
    LogSource(
        name="WATCHDOG",
        # unified_watchdog_*가 있으면 우선, 없으면 legacy watchdog_ 사용 (finder에서 처리)
        patterns=["unified_watchdog_", "watchdog_"],
        color="yellow",
        tail_lines=2,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="CLAUDE-WD",
        patterns=["claude_watchdog_"],
        color="yellow",
        tail_lines=2,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="VIDEO-DL-WD",
        patterns=["video_download_watchdog_"],
        color="yellow",
        tail_lines=2,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="CRAWL-WD",
        patterns=["crawl_watchdog_"],
        color="yellow",
        tail_lines=2,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="CMD-WD",
        patterns=["command_listener_watchdog_"],
        color="yellow",
        tail_lines=2,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="API-WD",
        patterns=["api_watchdog_"],
        color="yellow",
        tail_lines=3,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="STARTUP-API-WD",
        patterns=["startup_api_watchdog_"],
        color="yellow",
        tail_lines=3,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="STARTUP-WORKERS",
        patterns=["startup_browser_workers_"],
        color="yellow",
        tail_lines=3,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="CMD-LISTENER",
        patterns=["worker_command_listener_"],
        color="dark_cyan",
        tail_lines=5,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="DEV-RUNNER",
        patterns=["dev_runner_command_listener"],
        color="dark_cyan",
        tail_lines=10,
        admin_only=True,
        check_stale=False,
    ),
    LogSource(
        name="MERGE-ORCH",
        patterns=["merge-orchestrator_"],
        color="cyan",
        tail_lines=10,
        admin_only=True,
        check_stale=False,
    ),
]

# ---------------------------------------------------------------------------
# plan-runner 소스 (Redis 활성 runner 기반으로 동적 생성 — 별도 처리)
# ---------------------------------------------------------------------------
# plan-runner 로그 파일 패턴 (정적 fallback 전용)
PLAN_RUNNER_LOG_PATTERN = "plan-runner-*.log"
PLAN_RUNNER_STREAM_PATTERN = "plan-runner-stream-*.log"

# plan-runner 소스 색상
PLAN_RUNNER_COLOR = "white"
PLAN_RUNNER_STREAM_COLOR = "bright_black"
PLAN_RUNNER_TAIL = 10
PLAN_RUNNER_STREAM_TAIL = 5

# ---------------------------------------------------------------------------
# cleanup 필터 패턴 (SSOT — logs.ps1 Follow 모드도 동일 패턴 사용)
# ---------------------------------------------------------------------------
CLEANUP_FILTER_PATTERN = r"\[cleanup\]|heartbeat.*cleanup|stale.*runner|force_cleanup|_cleanup_process"

# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------


def get_public_safe_sources() -> list[LogSource]:
    """Public-safe 표면에 노출 가능한 로그 소스 목록을 반환한다."""
    return [s for s in LOG_SOURCES if s.public_safe]


def get_sources(admin: bool = False, public_safe: bool = False) -> list[LogSource]:
    """
    admin 모드 여부에 따라 표시할 로그 소스 목록을 반환한다.

    admin=False이면 admin_only=True 소스를 제외한다.
    public_safe=True이면 명시 allowlist만 반환한다.
    """
    if public_safe:
        return get_public_safe_sources()
    if admin:
        return list(LOG_SOURCES)
    return [s for s in LOG_SOURCES if not s.admin_only]


def get_source_by_name(name: str) -> Optional[LogSource]:
    """이름으로 LogSource를 조회한다. 없으면 None 반환."""
    for src in LOG_SOURCES:
        if src.name == name:
            return src
    return None
