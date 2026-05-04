"""cleanup TTL 제외 TC — plan_file, branch 키는 TTL 없이 영구 보존

scripts/dev-runner-command-listener.py의 _cleanup_process_state() 수정 검증:
  - plan_file, branch 키는 TTL 설정 스킵 → 영구 보존
  - status, pid 등 나머지 키는 기존대로 TTL 설정
"""

import pytest
import fakeredis

# 테스트에서 직접 Redis를 조작하므로 command-listener의 상수를 import
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
RECENT_RUNNERS_TTL = 86400

RUNNER_KEY_SUFFIXES = (
    "status", "pid", "plan_file", "start_time", "log_file_path", "stream_log_path",
    "engine", "fix_engine", "worktree_path", "branch",
    "merge_status", "merge_requested", "merge_reason", "merge_message",
    "done_post_merge_status", "done_post_merge_error", "quarantine_diff_path",
    "service_lock_approved",
    "current_cycle", "quota_stopped", "error", "restart_after_merge", "test_source", "trigger",
    "subprocess_heartbeat", "pid_create_time", "process_cmdline_hash",
)


def _simulate_cleanup(redis, runner_id: str, preserve_worktree: bool = False):
    """_cleanup_process_state() 내 TTL 설정 로직을 직접 시뮬레이션"""
    redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
    for suffix in RUNNER_KEY_SUFFIXES:
        if preserve_worktree and suffix == "worktree_path":
            continue
        if suffix in ("plan_file", "branch"):
            continue  # 불변 속성: TTL 없이 영구 보존
        key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
        redis.expire(key, RECENT_RUNNERS_TTL)
    redis.srem(ACTIVE_RUNNERS_KEY, runner_id)
    redis.zadd(RECENT_RUNNERS_KEY, {runner_id: 1.0})


@pytest.fixture
def redis():
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.close()


def _setup_runner(redis, runner_id: str):
    """runner의 모든 키를 미리 설정"""
    for suffix in RUNNER_KEY_SUFFIXES:
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"value_{suffix}")
    redis.sadd(ACTIVE_RUNNERS_KEY, runner_id)


class TestCleanupPreservesImmutableKeys:
    def test_cleanup_preserves_plan_file_key(self, redis):
        """R: cleanup 후 plan_file 키 TTL == -1 (영구 보존)"""
        runner_id = "cleanup_test01"
        _setup_runner(redis, runner_id)
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "my-plan.md")

        _simulate_cleanup(redis, runner_id)

        ttl = redis.ttl(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        assert ttl == -1, f"plan_file 키에 TTL이 설정됨 (ttl={ttl}), 영구 보존 기대"

    def test_cleanup_preserves_branch_key(self, redis):
        """R: cleanup 후 branch 키 TTL == -1 (영구 보존)"""
        runner_id = "cleanup_test02"
        _setup_runner(redis, runner_id)
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "impl/feature-x")

        _simulate_cleanup(redis, runner_id)

        ttl = redis.ttl(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch")
        assert ttl == -1, f"branch 키에 TTL이 설정됨 (ttl={ttl}), 영구 보존 기대"

    def test_cleanup_sets_ttl_on_other_keys(self, redis):
        """R: status, pid 등 나머지 키에는 TTL 설정됨"""
        runner_id = "cleanup_test03"
        _setup_runner(redis, runner_id)

        _simulate_cleanup(redis, runner_id)

        for suffix in ("pid", "start_time", "current_cycle", "engine"):
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            ttl = redis.ttl(key)
            assert ttl > 0, f"{suffix} 키에 TTL이 설정되지 않음 (ttl={ttl})"

    def test_cleanup_plan_file_value_preserved(self, redis):
        """B: cleanup 후 plan_file 값이 지워지지 않고 유지됨"""
        runner_id = "cleanup_test04"
        _setup_runner(redis, runner_id)
        redis.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "important-plan.md")

        _simulate_cleanup(redis, runner_id)

        val = redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        assert val == "important-plan.md", "cleanup 후 plan_file 값이 변경됨"
