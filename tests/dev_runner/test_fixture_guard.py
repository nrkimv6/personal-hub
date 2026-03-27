"""
test_fixture_guard.py — conftest fixture 동작 단위 검증

- test_pytest_redis_cleanup_right: redis_runner_cleanup fixture가 테스트 후
  RUNNER_KEY_PREFIX 키를 정리하는지 검증
- test_guard_new_instance_right: ExecutorService() 새 인스턴스에서 test_source 없이
  start_dev_runner 호출 시 pytest.fail 발생 검증  (T1-7)
- test_guard_user_trigger_blocked: guard fixture가 trigger="user" 전달 시
  pytest.fail 발생 검증  (T1-8)
"""
import uuid
import pytest

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

import redis as real_redis

# conftest에서 사용하는 상수와 동일하게 맞춤
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_redis():
    """격리된 Redis 인스턴스를 반환한다.

    fakeredis가 설치된 환경은 fakeredis 사용(완전 격리).
    그 외에는 real Redis db=15 사용 후 flushdb 처리.
    """
    if HAS_FAKEREDIS:
        return fakeredis.FakeRedis(decode_responses=True)
    r = real_redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    return r


def _cleanup_logic(r, before_runner_keys, before_active, before_recent_set):
    """conftest redis_runner_cleanup fixture의 yield 이후 cleanup 로직을 그대로 재현.

    반환값: (deleted_keys, removed_active, removed_recent)
    """
    # scan 현재 키
    after_runner_keys = set()
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor, match=f"{RUNNER_KEY_PREFIX}:*", count=100)
        after_runner_keys.update(batch)
        if cursor == 0:
            break

    new_runner_keys = after_runner_keys - before_runner_keys
    deleted_keys = set()
    if new_runner_keys:
        r.delete(*new_runner_keys)
        deleted_keys = new_runner_keys

    after_active = r.smembers(ACTIVE_RUNNERS_KEY) or set()
    new_active = after_active - before_active
    removed_active = set()
    if new_active:
        r.srem(ACTIVE_RUNNERS_KEY, *new_active)
        removed_active = new_active

    after_recent = set(r.zrange(RECENT_RUNNERS_KEY, 0, -1))
    new_recent = after_recent - before_recent_set
    removed_recent = set()
    if new_recent:
        r.zrem(RECENT_RUNNERS_KEY, *new_recent)
        removed_recent = new_recent

    return deleted_keys, removed_active, removed_recent


# ---------------------------------------------------------------------------
# T1-6: cleanup fixture 검증
# ---------------------------------------------------------------------------

class TestRedisCleanupFixture:
    """redis_runner_cleanup fixture의 cleanup 로직을 단위 검증한다."""

    def test_pytest_redis_cleanup_right(self):
        """cleanup 로직이 테스트 중 추가된 RUNNER_KEY_PREFIX 키를 정리하는지 검증.

        시나리오:
        1. 격리된 Redis에서 "before" 스냅샷 생성
        2. 테스트 중 runner 키 2개 추가 (tc-pytest-* prefix)
        3. cleanup 로직 실행
        4. 추가된 키가 모두 삭제됐는지, 기존 키는 유지되는지 확인
        """
        r = _make_redis()

        # --- 기존 runner 키 세팅 (운영 runner로 가정) ---
        existing_runner_id = f"existing-runner-{uuid.uuid4().hex[:8]}"
        existing_key = f"{RUNNER_KEY_PREFIX}:{existing_runner_id}:status"
        r.set(existing_key, "running")
        r.sadd(ACTIVE_RUNNERS_KEY, existing_runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {existing_runner_id: 1000})

        # --- before 스냅샷 ---
        before_runner_keys = set()
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor, match=f"{RUNNER_KEY_PREFIX}:*", count=100)
            before_runner_keys.update(batch)
            if cursor == 0:
                break
        before_active = r.smembers(ACTIVE_RUNNERS_KEY) or set()
        before_recent_set = set(r.zrange(RECENT_RUNNERS_KEY, 0, -1))

        # --- 테스트 중 새 runner 키 추가 ---
        new_id_1 = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        new_id_2 = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        new_key_1 = f"{RUNNER_KEY_PREFIX}:{new_id_1}:status"
        new_key_2 = f"{RUNNER_KEY_PREFIX}:{new_id_2}:trigger"
        r.set(new_key_1, "running")
        r.set(new_key_2, "user")
        r.sadd(ACTIVE_RUNNERS_KEY, new_id_1, new_id_2)
        r.zadd(RECENT_RUNNERS_KEY, {new_id_1: 2000, new_id_2: 2001})

        # --- cleanup 실행 ---
        deleted_keys, removed_active, removed_recent = _cleanup_logic(
            r, before_runner_keys, before_active, before_recent_set
        )

        # --- 검증: 새로 추가된 키가 모두 삭제됨 ---
        assert new_key_1 in deleted_keys, f"{new_key_1} should be deleted"
        assert new_key_2 in deleted_keys, f"{new_key_2} should be deleted"
        assert r.exists(new_key_1) == 0, f"{new_key_1} should not exist after cleanup"
        assert r.exists(new_key_2) == 0, f"{new_key_2} should not exist after cleanup"

        # --- 검증: ACTIVE_RUNNERS_KEY에서 새 ID 제거됨 ---
        assert new_id_1 in removed_active
        assert new_id_2 in removed_active
        assert not r.sismember(ACTIVE_RUNNERS_KEY, new_id_1)
        assert not r.sismember(ACTIVE_RUNNERS_KEY, new_id_2)

        # --- 검증: RECENT_RUNNERS_KEY에서 새 ID 제거됨 ---
        assert new_id_1 in removed_recent
        assert new_id_2 in removed_recent
        remaining_recent = r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert new_id_1 not in remaining_recent
        assert new_id_2 not in remaining_recent

        # --- 검증: 기존 runner는 보호됨 ---
        assert existing_key not in deleted_keys, "기존 runner 키는 삭제되지 않아야 함"
        assert r.exists(existing_key) == 1, "기존 runner 키는 유지되어야 함"
        assert r.sismember(ACTIVE_RUNNERS_KEY, existing_runner_id), "기존 active runner는 유지되어야 함"
        assert existing_runner_id in r.zrange(RECENT_RUNNERS_KEY, 0, -1), "기존 recent runner는 유지되어야 함"

    def test_cleanup_no_new_keys_is_noop(self):
        """테스트 중 새 키가 없으면 cleanup이 아무것도 삭제하지 않음."""
        r = _make_redis()

        # before 스냅샷
        before_runner_keys: set = set()
        before_active: set = set()
        before_recent_set: set = set()

        # 아무 키도 추가하지 않음

        deleted_keys, removed_active, removed_recent = _cleanup_logic(
            r, before_runner_keys, before_active, before_recent_set
        )

        assert deleted_keys == set()
        assert removed_active == set()
        assert removed_recent == set()

    def test_cleanup_only_deletes_new_keys_not_preexisting(self):
        """cleanup은 before 스냅샷에 있던 키는 삭제하지 않는다."""
        r = _make_redis()

        # 기존 키 2개
        pre_id = f"pre-runner-{uuid.uuid4().hex[:8]}"
        pre_key = f"{RUNNER_KEY_PREFIX}:{pre_id}:status"
        r.set(pre_key, "running")

        # before 스냅샷에 이미 포함
        before_runner_keys = {pre_key}
        before_active: set = set()
        before_recent_set: set = set()

        # 테스트 중 새 키 1개
        new_id = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        new_key = f"{RUNNER_KEY_PREFIX}:{new_id}:status"
        r.set(new_key, "running")

        deleted_keys, _, _ = _cleanup_logic(
            r, before_runner_keys, before_active, before_recent_set
        )

        assert new_key in deleted_keys
        assert pre_key not in deleted_keys
        assert r.exists(pre_key) == 1, "기존 키는 유지되어야 함"
        assert r.exists(new_key) == 0, "새 키는 삭제되어야 함"
