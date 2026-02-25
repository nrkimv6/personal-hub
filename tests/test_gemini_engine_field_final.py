"""
Gemini engine 필드 정합성 최종 검증 테스트 (Right-BICEP + CORRECT 원칙)

대상:
  - executor_service.start_dev_runner()  → engine 필드 응답 정합성
  - executor_service.get_process_status() → engine 필드 응답 정합성
  - RunStatusResponse 모델 필드 존재 및 타입 보증

fakeredis를 이용한 서비스 레이어 단위 테스트.
"""

import json
from datetime import datetime
from unittest.mock import patch

import fakeredis
import fakeredis.aioredis
import pytest

from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from app.modules.dev_runner.services.executor_service import ExecutorService

RESULTS_KEY = "plan-runner:command_results"
STATE_KEY = "plan-runner:state"
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis_pair():
    """동기 / 비동기 fakeredis 쌍을 반환"""
    sync_r = fakeredis.FakeRedis(decode_responses=True)
    async_r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return {"sync": sync_r, "async": async_r}


@pytest.fixture
def svc(fake_redis_pair):
    """executor_service 인스턴스에 fakeredis 주입"""
    instance = ExecutorService.__new__(ExecutorService)
    instance.redis_client = fake_redis_pair["sync"]
    instance.async_redis = fake_redis_pair["async"]
    return instance


# ---------------------------------------------------------------------------
# 1. Right – 정상 동작
# ---------------------------------------------------------------------------

class TestRight:
    """Right: 정상 동작 확인"""

    @pytest.mark.asyncio
    async def test_start_with_gemini_returns_gemini_engine(self, svc, fake_redis_pair):
        """start_dev_runner engine='gemini' → 응답 engine 필드가 'gemini'여야 한다"""
        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True, "message": "Started"}))
        await async_r.set(STATE_KEY + ":pid", "12345")
        await async_r.set(STATE_KEY + ":plan_file", "test.md")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="test.md", engine="gemini")
        resp = await svc.start_dev_runner(req)

        assert resp.engine == "gemini"

    def test_get_status_engine_not_none_when_running(self, svc, fake_redis_pair):
        """get_process_status: 실행 중일 때 engine 필드가 None이 아니어야 한다"""
        sync_r = fake_redis_pair["sync"]
        now = datetime.now().isoformat()

        sync_r.set(HEARTBEAT_KEY, now)
        sync_r.set(STATE_KEY + ":status", "running")
        sync_r.set(STATE_KEY + ":pid", "12345")
        sync_r.set(STATE_KEY + ":start_time", now)
        sync_r.set(STATE_KEY + ":engine", "gemini")

        resp = svc.get_process_status()

        assert resp.engine is not None
        assert resp.engine == "gemini"


# ---------------------------------------------------------------------------
# 2. Boundary – 경계값
# ---------------------------------------------------------------------------

class TestBoundary:
    """Boundary: 경계값 처리"""

    @pytest.mark.asyncio
    async def test_start_with_empty_engine_returns_none_engine(self, svc, fake_redis_pair):
        """engine='' (빈 문자열) 요청 → 응답 engine 필드는 None 또는 기본값"""
        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True}))
        await async_r.set(STATE_KEY + ":pid", "1")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="test.md", engine="")
        resp = await svc.start_dev_runner(req)

        # 빈 문자열은 falsy → engine 필드가 세팅되지 않으므로 request.engine(빈 문자열) 그대로 반환
        # start_dev_runner는 request.engine을 직접 반환하므로 빈 문자열이 올 수 있음
        # 이때 프론트엔드는 None/""를 claude 폴백으로 처리해야 함
        assert resp.engine == "" or resp.engine is None

    @pytest.mark.asyncio
    async def test_start_with_none_engine_defaults_gracefully(self, svc, fake_redis_pair):
        """engine=None → 응답 engine 필드가 None이어도 서비스 오류 없음"""
        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True}))
        await async_r.set(STATE_KEY + ":pid", "2")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="test.md", engine=None)
        resp = await svc.start_dev_runner(req)

        # engine=None이면 command에 engine 키가 없음 → RunStatusResponse(engine=None)
        assert resp.engine is None
        assert isinstance(resp, RunStatusResponse)


# ---------------------------------------------------------------------------
# 3. Inverse – 역방향
# ---------------------------------------------------------------------------

class TestInverse:
    """Inverse: claude 엔진 요청 시 gemini로 표시되지 않음"""

    @pytest.mark.asyncio
    async def test_start_with_claude_engine_not_gemini(self, svc, fake_redis_pair):
        """engine='claude' 요청 → 응답 engine이 'gemini'가 아니어야 한다"""
        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True}))
        await async_r.set(STATE_KEY + ":pid", "3")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="test.md", engine="claude")
        resp = await svc.start_dev_runner(req)

        assert resp.engine != "gemini"
        assert resp.engine == "claude"


# ---------------------------------------------------------------------------
# 4. Cross-check – 교차 검증
# ---------------------------------------------------------------------------

class TestCrossCheck:
    """Cross-check: start 응답 engine과 status 응답 engine 일치 확인"""

    @pytest.mark.asyncio
    async def test_start_and_status_engine_match(self, svc, fake_redis_pair):
        """start 응답 engine 필드와 status 응답 engine 필드가 일치해야 한다"""
        async_r = fake_redis_pair["async"]
        sync_r = fake_redis_pair["sync"]
        now = datetime.now().isoformat()

        # start 준비
        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True}))
        await async_r.set(STATE_KEY + ":pid", "9999")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="test.md", engine="gemini")
        start_resp = await svc.start_dev_runner(req)

        # status 조회를 위한 Redis 상태 세팅 (listener가 저장한다고 가정)
        sync_r.set(HEARTBEAT_KEY, now)
        sync_r.set(STATE_KEY + ":status", "running")
        sync_r.set(STATE_KEY + ":pid", "9999")
        sync_r.set(STATE_KEY + ":start_time", now)
        sync_r.set(STATE_KEY + ":engine", "gemini")

        status_resp = svc.get_process_status()

        assert start_resp.engine == status_resp.engine


# ---------------------------------------------------------------------------
# 5. Error – 에러 조건
# ---------------------------------------------------------------------------

class TestError:
    """Error: 에러 조건 처리"""

    @pytest.mark.asyncio
    async def test_already_running_returns_409(self, svc, fake_redis_pair):
        """이미 실행 중일 때 다른 엔진으로 start 요청 시 409 Conflict"""
        from fastapi import HTTPException

        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        # running 상태 세팅
        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.set(STATE_KEY + ":status", "running")
        await async_r.set(STATE_KEY + ":pid", "55555")

        req = RunRequest(plan_file="test.md", engine="gemini")
        with pytest.raises(HTTPException) as exc_info:
            await svc.start_dev_runner(req)

        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 6. Performance – Race condition 없음
# ---------------------------------------------------------------------------

class TestPerformance:
    """Performance: start 직후 즉시 engine 필드 반환 (race condition 없음)"""

    @pytest.mark.asyncio
    async def test_engine_field_returned_immediately_after_start(self, svc, fake_redis_pair):
        """start 직후 응답에 engine 필드가 즉시 올바르게 포함되어야 한다"""
        async_r = fake_redis_pair["async"]
        now = datetime.now().isoformat()

        await async_r.set(HEARTBEAT_KEY, now)
        await async_r.rpush(RESULTS_KEY, json.dumps({"success": True}))
        await async_r.set(STATE_KEY + ":pid", "77777")
        await async_r.set(STATE_KEY + ":start_time", now)

        req = RunRequest(plan_file="plan.md", engine="gemini")
        resp = await svc.start_dev_runner(req)

        # Redis 폴링 없이 즉시 request.engine 값으로 반환
        assert resp.engine == "gemini"
        assert resp.running is True


# ---------------------------------------------------------------------------
# 7. CORRECT – Conformance (형식 일치)
# ---------------------------------------------------------------------------

class TestConformance:
    """CORRECT - Conformance: engine 필드 값이 허용 범위 내인지 타입 검증"""

    VALID_ENGINE_VALUES = {"claude", "gemini", None}

    def test_get_status_engine_is_valid_value(self, svc, fake_redis_pair):
        """get_process_status engine 필드는 'claude', 'gemini', None 중 하나여야 한다"""
        sync_r = fake_redis_pair["sync"]
        now = datetime.now().isoformat()

        sync_r.set(HEARTBEAT_KEY, now)
        sync_r.set(STATE_KEY + ":status", "running")
        sync_r.set(STATE_KEY + ":pid", "1234")
        sync_r.set(STATE_KEY + ":start_time", now)
        sync_r.set(STATE_KEY + ":engine", "claude")

        resp = svc.get_process_status()

        assert resp.engine in self.VALID_ENGINE_VALUES

    def test_get_status_not_running_engine_is_valid(self, svc, fake_redis_pair):
        """not running 상태에서도 engine은 허용 범위 내여야 한다"""
        sync_r = fake_redis_pair["sync"]
        sync_r.set(HEARTBEAT_KEY, datetime.now().isoformat())
        sync_r.set(STATE_KEY + ":engine", "gemini")
        # status 미설정 → not running

        resp = svc.get_process_status()

        assert resp.engine in self.VALID_ENGINE_VALUES


# ---------------------------------------------------------------------------
# 8. CORRECT – Existence (존재 보장)
# ---------------------------------------------------------------------------

class TestExistence:
    """CORRECT - Existence: RunStatusResponse에 engine 필드 항상 존재"""

    def test_run_status_response_has_engine_field(self):
        """RunStatusResponse 모델에 engine 필드가 정의되어 있어야 한다"""
        fields = RunStatusResponse.model_fields
        assert "engine" in fields

    def test_run_status_response_engine_default_is_none(self):
        """RunStatusResponse 기본 인스턴스에서 engine 필드는 None이어야 한다"""
        resp = RunStatusResponse(running=False)
        assert resp.engine is None

    def test_run_status_response_engine_accepts_gemini(self):
        """RunStatusResponse engine='gemini' 설정이 오류 없이 동작해야 한다"""
        resp = RunStatusResponse(running=True, engine="gemini")
        assert resp.engine == "gemini"

    def test_get_process_status_always_returns_run_status_response(self, svc, fake_redis_pair):
        """get_process_status는 항상 RunStatusResponse 인스턴스를 반환해야 한다"""
        resp = svc.get_process_status()
        assert isinstance(resp, RunStatusResponse)
        # engine 필드는 접근 가능해야 함 (AttributeError 없음)
        _ = resp.engine
