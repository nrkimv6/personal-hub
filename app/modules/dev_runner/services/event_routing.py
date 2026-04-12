"""event_routing — Redis 키/채널 라우팅 순수 함수 + 공유 상수

B 도메인: _classify_key, _extract_runner_id, _extract_runner_id_from_channel
상태 없음. Redis 불필요. 단위 테스트만으로 검증 가능.
"""
from typing import Optional

# ─── Redis 연결 상수 ─────────────────────────────────────────────────────────
REDIS_HOST = "localhost"
REDIS_PORT = 6379

# ─── Redis 키 상수 ───────────────────────────────────────────────────────────
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
REDIS_STATE_KEY = "plan-runner:state"
PLAN_FILE_ALL = "__ALL_PLANS__"  # 전체실행 sentinel (command-listener와 공유)
_LEGACY_ALL = "ALL"  # 하위 호환

# ─── SSE 채널 상수 ───────────────────────────────────────────────────────────
KEYEVENT_CHANNEL = "__keyevent@0__:set"
LOG_CHANNEL_PATTERN = "plan-runner:logs:*"
MERGE_LOG_CHANNEL_PATTERN = "plan-runner:merge-log:*"

# ─── 최근 러너 상수 (event_payload · event_service 양쪽에서 사용) ───────────
MAX_RECENT_IN_SSE = 20   # SSE status 이벤트에 포함할 RECENT 러너 최대 수
MAX_RECENT_RUNNERS = 100  # sorted set 크기 상한

# ─── 키 이벤트 매핑 ──────────────────────────────────────────────────────────
# 키가 이 접두사로 시작하면 해당 이벤트를 발행한다.
KEY_EVENT_MAP = {
    f"{RUNNER_KEY_PREFIX}:": "status",
    f"{REDIS_STATE_KEY}:current_task_text": "tracking",
    f"{REDIS_STATE_KEY}:current_task_plan_file": "plan_changed",
}


# ─── 라우팅 순수 함수 ────────────────────────────────────────────────────────

def classify_key(key: str) -> Optional[str]:
    """변경된 Redis 키로부터 SSE 이벤트 타입 결정. 무관한 키는 None."""
    if key == f"{REDIS_STATE_KEY}:current_task_text":
        return "tracking"
    if key == f"{REDIS_STATE_KEY}:current_task_plan_file":
        return "plan_changed"
    if key.startswith(f"{RUNNER_KEY_PREFIX}:"):
        parts = key.split(":")
        if len(parts) >= 4:
            return "status"
    return None


def extract_runner_id(key: str) -> Optional[str]:
    """키에서 runner_id 추출 (status 이벤트 전용).

    Examples:
        "plan-runner:runners:abc123:status" → "abc123"
    """
    parts = key.split(":")
    if len(parts) >= 4:
        return parts[2]
    return None


def extract_runner_id_from_channel(channel: str) -> Optional[str]:
    """로그 채널명에서 runner_id 추출.

    Examples:
        "plan-runner:logs:abc123"      → "abc123"
        "plan-runner:merge-log:def456" → "def456"
    """
    if not channel or ":" not in channel:
        return None
    runner_id = channel.split(":")[-1]
    return runner_id if runner_id else None
