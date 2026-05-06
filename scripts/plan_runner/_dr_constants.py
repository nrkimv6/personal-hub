"""_dr_constants.py — dev-runner-command-listener 상수 모듈"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject

import os
from pathlib import Path

from _dr_merge_state import ACTIVE_STATUSES

# Redis 설정
REDIS_HOST = "localhost"
REDIS_PORT = 6379
COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"  # sorted set: score=종료 timestamp
PLAN_FILE_ALL = "__ALL_PLANS__"  # 전체실행 sentinel — plan_file 미지정 시 Redis에 저장
_LEGACY_ALL = "ALL"  # 하위 호환: 이전 버전에서 저장된 "ALL" 값 인식용
SESSION_ID_KEY_PREFIX = "plan-runner:session:"  # fused 세션 ID 저장 키 접두사 (runner_id → session_id 매핑)
# RECENT runner 보존 TTL 계약 (API와 동일 키/기본값 사용)
_ENV_RECENT_RUNNERS_TTL = "DEV_RUNNER_RECENT_TTL_SECONDS"
_DEFAULT_RECENT_RUNNERS_TTL = 86400  # 24시간


def _resolve_recent_runners_ttl() -> int:
    raw = os.environ.get(_ENV_RECENT_RUNNERS_TTL, str(_DEFAULT_RECENT_RUNNERS_TTL))
    try:
        ttl = int(str(raw).strip())
        # 0/음수는 보존 계약 위반이므로 기본값(24h)으로 강제 fallback
        return ttl if ttl > 0 else _DEFAULT_RECENT_RUNNERS_TTL
    except (TypeError, ValueError):
        # 비정수 입력도 기본값(24h) fallback
        return _DEFAULT_RECENT_RUNNERS_TTL


RECENT_RUNNERS_TTL = _resolve_recent_runners_ttl()
# recent-meta 보존 TTL — cleanup 후에도 trigger/accepted_at/started_at 조회 가능 시간 (1시간)
RECENT_META_TTL = 3600
ADMIN_API_PORT = int(os.environ.get("ADMIN_API_PORT", "8001"))

# per-runner 키 suffix 전체 목록 — app/modules/dev_runner/services/executor_service.py의 RUNNER_KEY_SUFFIXES와 동일
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch",
    "merge_status", "merge_requested", "merge_reason", "merge_message",
    "done_post_merge_status", "done_post_merge_error", "quarantine_diff_path",
    "service_lock_approved",
    "current_cycle", "execution_count", "quota_stopped", "error", "restart_after_merge", "exit_reason", "test_source", "trigger",
    "subprocess_heartbeat", "pid_create_time", "process_cmdline_hash", "reflect_final_path",
    "accepted_at", "accepted_source", "started_at",  # 관측 메타 키 (Phase 1)
    # profile 관련 키 (신규 4개) — redis_connection.py의 RUNNER_KEY_SUFFIXES와 동기화 필수
    "profile", "profile_env_key", "profile_config_dir", "profile_extra_env",
    "worktree_exists", "branch_exists", "branch_merged_to_main", "metadata_checked_at",
)
def _read_zombie_grace_seconds(default: int = 240) -> int:
    """좀비 감지 유예 시간(env override) 파싱."""
    raw = os.environ.get("DEV_RUNNER_ZOMBIE_GRACE_SECONDS")
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


ZOMBIE_GRACE_SECONDS = _read_zombie_grace_seconds()  # 기본 240초, 테스트/운영에서 env로 오버라이드 가능
SUBPROCESS_HEARTBEAT_TTL = 120  # subprocess heartbeat TTL(초) — listener 10초 주기 × 12회 miss 허용, reconnect 안전 창 2배
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 갱신 주기 (초)
HEARTBEAT_TTL = 30  # heartbeat 만료 시간 (초, 3회 미갱신 시 만료)

# merge 활성 상태 — cleanup 보호 가드 및 reconnect 복구 조건에 사용
MERGE_ACTIVE_STATUSES = tuple(sorted(ACTIVE_STATUSES))

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts/plan_runner/ → scripts/ → project root


def _resolve_worktree_root() -> Path:
    """PROJECT_ROOT 기반으로 nested .worktrees escape한 root 반환."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            git_root = Path(result.stdout.strip())
            parts = list(git_root.parts)
            if ".worktrees" in parts:
                i = parts.index(".worktrees")
                candidate = Path(*parts[:i])
                if (candidate / ".git").exists():
                    return candidate
            return git_root
    except Exception:
        pass
    return PROJECT_ROOT


WORKTREE_BASE_DIR = _resolve_worktree_root() / ".worktrees"
OWNERSHIP_SNAPSHOT_DIR = PROJECT_ROOT / "logs" / "dev_runner" / "ownership"
WTOOLS_BASE_DIR = Path("D:/work/project/service/wtools")
PLAN_RUNNER_MODULE_PATH = WTOOLS_BASE_DIR / "common/tools/plan-runner"
PLAN_RUNNER_PYTHON = PLAN_RUNNER_MODULE_PATH / ".venv/Scripts/python.exe"
LOG_DIR = WTOOLS_BASE_DIR / "common/logs"

LOG_CHANNEL_PREFIX = "plan-runner:logs"

# REDIS_DB 동적 접근자 (--redis-db 인자로 런타임에 오버라이드 가능)
_state = {"redis_db": 0}


def get_redis_db() -> int:
    return _state["redis_db"]


def set_redis_db(db: int) -> None:
    _state["redis_db"] = db


def get_admin_api_base() -> str:
    return f"http://localhost:{ADMIN_API_PORT}/api"
