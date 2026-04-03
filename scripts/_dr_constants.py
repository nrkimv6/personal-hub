"""_dr_constants.py — dev-runner-command-listener 상수 모듈"""
import os
from pathlib import Path

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
RECENT_RUNNERS_TTL = 3600  # 1시간 (초) — app/modules/dev_runner/services/redis_connection.py와 동일하게 유지
ADMIN_API_PORT = int(os.environ.get("ADMIN_API_PORT", "8001"))

# per-runner 키 suffix 전체 목록 — app/modules/dev_runner/services/executor_service.py의 RUNNER_KEY_SUFFIXES와 동일
RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch", "merge_status", "merge_requested",
    "current_cycle", "quota_stopped", "error", "restart_after_merge", "exit_reason", "stop_stage", "test_source", "trigger",
)
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
HEARTBEAT_INTERVAL = 10  # heartbeat 갱신 주기 (초)
HEARTBEAT_TTL = 30  # heartbeat 만료 시간 (초, 3회 미갱신 시 만료)

# merge 활성 상태 — cleanup 보호 가드 및 reconnect 복구 조건에 사용
MERGE_ACTIVE_STATUSES = ("pre_merge", "queued", "merging", "pending_merge", "resolving", "testing", "fixing")

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
WORKTREE_BASE_DIR = PROJECT_ROOT / ".worktrees"
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
