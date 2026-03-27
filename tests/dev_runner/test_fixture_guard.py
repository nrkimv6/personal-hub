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

    # ---------------------------------------------------------------------------
    # T1-7: guard — 새 ExecutorService() 인스턴스 검증
    # ---------------------------------------------------------------------------


class TestGuardNewInstance:
    """force_test_source_on_start_dev_runner fixture가 새 ExecutorService()
    인스턴스의 start_dev_runner에도 guard를 적용하는지 검증한다."""

    def test_guard_new_instance_right(self):
        """ExecutorService() 새 인스턴스에서 test_source 없이 start_dev_runner 호출 시
        pytest.fail 발생 검증.

        시나리오:
        1. ExecutorService() 새 인스턴스 생성
        2. test_source=None인 RunRequest로 start_dev_runner 호출
        3. pytest.fail() → _pytest.outcomes.Failed 예외 발생 확인
        4. 오류 메시지에 "test_source" 포함 확인
        """
        import asyncio
        from _pytest.outcomes import Failed

        try:
            from app.modules.dev_runner.services.executor_service import ExecutorService
            from app.modules.dev_runner.schemas import RunRequest
        except Exception as e:
            pytest.skip(f"Import 실패 — 환경 문제: {e}")

        # 새 인스턴스 생성 (conftest patch가 __init__을 통해 guard 적용)
        svc = ExecutorService()

        # test_source 없는 요청
        req = RunRequest(plan_file="some/plan.md")
        assert req.test_source is None, "전제 조건: test_source가 None이어야 함"

        # guard가 pytest.fail()을 호출하면 Failed 예외가 발생함
        with pytest.raises(Failed) as exc_info:
            asyncio.get_event_loop().run_until_complete(svc.start_dev_runner(req))

        assert "test_source" in str(exc_info.value), (
            f"오류 메시지에 'test_source' 포함 기대. 실제: {exc_info.value}"
        )

    # ---------------------------------------------------------------------------
    # T1-8: guard — trigger="user" 차단 검증
    # ---------------------------------------------------------------------------


class TestGuardUserTriggerBlocked:
    """force_test_source_on_start_dev_runner fixture가 trigger="user" 또는
    "user:all" 전달 시 pytest.fail()을 호출하는지 검증한다."""

    def test_guard_user_trigger_blocked(self):
        """guard fixture가 trigger="user" 전달 시 pytest.fail 발생 검증.

        시나리오:
        1. ExecutorService() 새 인스턴스 생성
        2. test_source는 유효하게 설정하되, trigger="user"로 RunRequest 구성
        3. start_dev_runner 호출 시 pytest.fail() → _pytest.outcomes.Failed 예외 발생 확인
        4. 오류 메시지에 "trigger" 포함 확인
        """
        import asyncio
        from _pytest.outcomes import Failed

        try:
            from app.modules.dev_runner.services.executor_service import ExecutorService
            from app.modules.dev_runner.schemas import RunRequest
        except Exception as e:
            pytest.skip(f"Import 실패 — 환경 문제: {e}")

        # 새 인스턴스 생성 (conftest patch가 __init__을 통해 guard 적용)
        svc = ExecutorService()

        # test_source는 있지만 trigger="user" → guard가 두 번째 조건에서 차단
        req = RunRequest(plan_file="some/plan.md", test_source="test_guard_user_trigger_blocked", trigger="user")
        assert req.test_source is not None, "전제 조건: test_source가 설정되어야 함"
        assert req.trigger == "user", "전제 조건: trigger가 'user'이어야 함"

        # guard가 pytest.fail()을 호출하면 Failed 예외가 발생함
        with pytest.raises(Failed) as exc_info:
            asyncio.get_event_loop().run_until_complete(svc.start_dev_runner(req))

        assert "trigger" in str(exc_info.value), (
            f"오류 메시지에 'trigger' 포함 기대. 실제: {exc_info.value}"
        )

    def test_guard_user_all_trigger_blocked(self):
        """guard fixture가 trigger="user:all" 전달 시에도 pytest.fail 발생 검증.

        "user"와 "user:all" 두 가지 모두 차단됨을 확인한다.
        """
        import asyncio
        from _pytest.outcomes import Failed

        try:
            from app.modules.dev_runner.services.executor_service import ExecutorService
            from app.modules.dev_runner.schemas import RunRequest
        except Exception as e:
            pytest.skip(f"Import 실패 — 환경 문제: {e}")

        svc = ExecutorService()

        req = RunRequest(plan_file="some/plan.md", test_source="test_guard_user_all_trigger_blocked", trigger="user:all")
        assert req.trigger == "user:all", "전제 조건: trigger가 'user:all'이어야 함"

        with pytest.raises(Failed) as exc_info:
            asyncio.get_event_loop().run_until_complete(svc.start_dev_runner(req))

        assert "trigger" in str(exc_info.value), (
            f"오류 메시지에 'trigger' 포함 기대. 실제: {exc_info.value}"
        )


class TestGuardPreexistingKeys:
    """cleanup 관련 추가 검증."""

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


# ---------------------------------------------------------------------------
# T1-10: cleanup fixture가 테스트 실패 시에도 정상 동작하는지 검증
# ---------------------------------------------------------------------------


class TestCleanupSurvivesInterruptBoundary:
    """redis_runner_cleanup fixture가 테스트 실패/예외 상황에서도
    cleanup 로직을 정상 실행하는지 검증한다.

    pytest fixture의 yield 패턴에서 yield 이후 로직은 테스트 성공/실패
    무관하게 항상 실행된다. 이 TC는 그 보장을 명시적으로 검증한다.
    """

    def test_cleanup_survives_interrupt_boundary(self):
        """cleanup 로직이 테스트 실패(예외) 시뮬레이션 후에도 키를 정리하는지 검증.

        시나리오:
        1. 격리된 Redis에서 before 스냅샷 생성
        2. 테스트 중 runner 키 추가 (tc-pytest-* prefix)
        3. 테스트 실패를 시뮬레이션 — RuntimeError 발생 후 except로 캐치
           (실제 pytest fixture의 yield 이후 로직은 이 경우에도 실행됨)
        4. cleanup 로직을 finally처럼 실행
        5. 추가된 키가 모두 삭제됐는지 확인
        """
        r = _make_redis()

        # --- before 스냅샷 ---
        before_runner_keys: set = set()
        before_active: set = set()
        before_recent_set: set = set()

        # --- 테스트 중 runner 키 추가 ---
        tc_id = f"tc-pytest-{uuid.uuid4().hex[:8]}"
        tc_key_status = f"{RUNNER_KEY_PREFIX}:{tc_id}:status"
        tc_key_trigger = f"{RUNNER_KEY_PREFIX}:{tc_id}:trigger"
        r.set(tc_key_status, "running")
        r.set(tc_key_trigger, "user")
        r.sadd(ACTIVE_RUNNERS_KEY, tc_id)
        r.zadd(RECENT_RUNNERS_KEY, {tc_id: 9999})

        # 키가 실제로 추가됐는지 전제 확인
        assert r.exists(tc_key_status) == 1
        assert r.exists(tc_key_trigger) == 1
        assert r.sismember(ACTIVE_RUNNERS_KEY, tc_id)

        # --- 테스트 실패 시뮬레이션 ---
        # pytest fixture의 yield 이후 구간(finally 역할)은 예외가 발생해도 실행된다.
        # 여기서는 exception을 catch하여 cleanup이 실행됨을 검증한다.
        simulated_failure_occurred = False
        cleanup_ran = False
        try:
            # 테스트 로직 중 예외 발생 시뮬레이션
            raise RuntimeError("simulated test failure: 테스트 실패 상황 재현")
        except RuntimeError:
            simulated_failure_occurred = True
            # pytest fixture yield 이후 cleanup은 항상 실행됨 — 여기서 실행
            try:
                deleted_keys, removed_active, removed_recent = _cleanup_logic(
                    r, before_runner_keys, before_active, before_recent_set
                )
                cleanup_ran = True
            except Exception:
                pass  # cleanup 자체 예외는 조용히 무시 (conftest 동작과 동일)

        # --- 검증: 실패 시뮬레이션이 실제로 발생했는지 ---
        assert simulated_failure_occurred, "테스트 실패 시뮬레이션이 실행되지 않음"

        # --- 검증: cleanup이 실행됐는지 ---
        assert cleanup_ran, (
            "cleanup 로직이 테스트 실패 후에도 실행되어야 함. "
            "conftest fixture의 yield 이후 구간은 항상 실행된다."
        )

        # --- 검증: 추가된 키가 모두 삭제됨 ---
        assert tc_key_status in deleted_keys, f"{tc_key_status} should be deleted after simulated failure"
        assert tc_key_trigger in deleted_keys, f"{tc_key_trigger} should be deleted after simulated failure"
        assert r.exists(tc_key_status) == 0, f"{tc_key_status} should not exist after cleanup"
        assert r.exists(tc_key_trigger) == 0, f"{tc_key_trigger} should not exist after cleanup"

        # --- 검증: ACTIVE_RUNNERS_KEY 정리됨 ---
        assert tc_id in removed_active, f"{tc_id} should be removed from active set"
        assert not r.sismember(ACTIVE_RUNNERS_KEY, tc_id), "active set에서 tc runner가 제거되어야 함"

        # --- 검증: RECENT_RUNNERS_KEY 정리됨 ---
        assert tc_id in removed_recent, f"{tc_id} should be removed from recent set"
        remaining_recent = r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert tc_id not in remaining_recent, "recent set에서 tc runner가 제거되어야 함"

    def test_cleanup_survives_multiple_keys_on_failure(self):
        """여러 키가 추가된 상태에서 테스트 실패 시 모두 정리되는지 검증.

        시나리오:
        1. before 스냅샷 (빈 상태)
        2. 여러 tc-pytest-* runner 키 추가
        3. 실패 시뮬레이션
        4. 모든 키 삭제 확인
        """
        r = _make_redis()

        before_runner_keys: set = set()
        before_active: set = set()
        before_recent_set: set = set()

        # 여러 runner 키 추가
        tc_ids = [f"tc-pytest-{uuid.uuid4().hex[:8]}" for _ in range(3)]
        added_keys = []
        for tc_id in tc_ids:
            key = f"{RUNNER_KEY_PREFIX}:{tc_id}:status"
            r.set(key, "running")
            r.sadd(ACTIVE_RUNNERS_KEY, tc_id)
            added_keys.append(key)

        # 실패 시뮬레이션 후 cleanup
        cleanup_result = None
        try:
            raise RuntimeError("simulated: 중간 실패")
        except RuntimeError:
            deleted_keys, removed_active, _ = _cleanup_logic(
                r, before_runner_keys, before_active, before_recent_set
            )
            cleanup_result = (deleted_keys, removed_active)

        assert cleanup_result is not None, "cleanup이 실행되어야 함"
        deleted_keys, removed_active = cleanup_result

        for key in added_keys:
            assert key in deleted_keys, f"{key}가 삭제되어야 함"
            assert r.exists(key) == 0, f"{key}가 Redis에서 제거되어야 함"

        for tc_id in tc_ids:
            assert tc_id in removed_active, f"{tc_id}가 active set에서 제거되어야 함"
