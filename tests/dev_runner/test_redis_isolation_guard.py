"""Redis 격리 guard 동작 테스트 (Phase T1 #23)

conftest.py의 block_trigger_user_direct_write fixture가
올바르게 작동하는지 검증한다.

참고: block_trigger_user_direct_write는 비autouse fixture이므로
      명시적으로 사용하는 테스트에서만 활성화됨.
      E2E 테스트는 allow_prod_redis 마커로 실서버 Redis를 사용.

TC 목록:
- test_fakeredis_trigger_user_write_blocked: 가드 활성 시 :trigger='user' 기록 차단 확인
- test_fakeredis_trigger_user_all_write_blocked: :trigger='user:all' 기록 차단 확인
- test_fakeredis_non_user_trigger_allowed: :trigger='tc:test' 기록 허용 확인
- test_fakeredis_non_trigger_key_user_value_allowed: :trigger 패턴 아닌 키는 허용
- test_fakeredis_trigger_user_without_guard: 가드 없으면 trigger='user' 기록 허용
"""
import pytest
import fakeredis
import fakeredis.aioredis


class TestRedisIsolationGuard:
    """block_trigger_user_direct_write fixture 동작 검증"""

    def test_fakeredis_trigger_user_write_blocked(self, block_trigger_user_direct_write):
        """E: 가드 활성화 시 fakeredis :trigger='user' 기록 → pytest.fail"""
        r = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "test-guard-check"

        with pytest.raises(pytest.fail.Exception) as exc_info:
            r.set(f"plan-runner:runners:{runner_id}:trigger", "user")

        assert "trigger" in str(exc_info.value).lower()

    def test_fakeredis_trigger_user_all_write_blocked(self, block_trigger_user_direct_write):
        """E: 가드 활성화 시 fakeredis :trigger='user:all' 기록 → pytest.fail"""
        r = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "test-guard-check-all"

        with pytest.raises(pytest.fail.Exception):
            r.set(f"plan-runner:runners:{runner_id}:trigger", "user:all")

    def test_fakeredis_non_user_trigger_allowed(self, block_trigger_user_direct_write):
        """R: 가드 활성화 시 :trigger='tc:test' 기록 → 허용 (차단 안 됨)"""
        r = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "test-guard-tc"
        r.set(f"plan-runner:runners:{runner_id}:trigger", "tc:pytest-guard")
        assert r.get(f"plan-runner:runners:{runner_id}:trigger") == "tc:pytest-guard"

    def test_fakeredis_non_trigger_key_user_value_allowed(self, block_trigger_user_direct_write):
        """R: :trigger 패턴 아닌 키에 'user' 값 → 허용 (차단 안 됨)"""
        r = fakeredis.FakeRedis(decode_responses=True)
        r.set("plan-runner:runners:test:status", "user")
        assert r.get("plan-runner:runners:test:status") == "user"

    def test_fakeredis_trigger_user_without_guard(self):
        """R: 가드 미사용 시 trigger='user' 기록 허용 (guard는 opt-in)"""
        r = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "test-no-guard"
        # block_trigger_user_direct_write fixture 없음 → 차단 없음
        r.set(f"plan-runner:runners:{runner_id}:trigger", "user")
        assert r.get(f"plan-runner:runners:{runner_id}:trigger") == "user"

    @pytest.mark.asyncio
    async def test_async_fakeredis_trigger_user_write_blocked(self, block_trigger_user_direct_write):
        """E: 가드 활성화 시 async fakeredis :trigger='user' 기록도 pytest.fail"""
        r = fakeredis.aioredis.FakeRedis(decode_responses=True)
        runner_id = "test-async-guard-check"

        with pytest.raises(pytest.fail.Exception) as exc_info:
            await r.set(f"plan-runner:runners:{runner_id}:trigger", "user")

        assert "trigger" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_async_fakeredis_non_user_trigger_allowed(self, block_trigger_user_direct_write):
        """R: 가드 활성화 시 async fakeredis :trigger='tc:test' 기록은 허용"""
        r = fakeredis.aioredis.FakeRedis(decode_responses=True)
        runner_id = "test-async-guard-tc"
        await r.set(f"plan-runner:runners:{runner_id}:trigger", "tc:pytest-guard")
        assert await r.get(f"plan-runner:runners:{runner_id}:trigger") == "tc:pytest-guard"

    @pytest.mark.asyncio
    async def test_async_fakeredis_trigger_user_without_guard(self):
        """R: async 가드 미사용 시 trigger='user' 기록 허용 (guard는 opt-in)"""
        r = fakeredis.aioredis.FakeRedis(decode_responses=True)
        runner_id = "test-async-no-guard"
        await r.set(f"plan-runner:runners:{runner_id}:trigger", "user")
        assert await r.get(f"plan-runner:runners:{runner_id}:trigger") == "user"
