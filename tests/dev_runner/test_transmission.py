import json
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest

class TestTransmissionPayload:
    """HTTP 발신(Redis 명령 전송) 전 페이로드 형식 Mock 테스트"""

    @pytest.fixture
    def executor_service(self):
        svc = ExecutorService()
        svc.async_redis = AsyncMock()
        # Mocking the heartbeat check to pass
        async def mock_get(key):
            if key == "plan-runner:listener:heartbeat":
                return "alive"
            if "pid" in key:
                return "12345"
            return None
        
        svc.async_redis.get = mock_get
        # Mocking the result of command start
        svc.async_redis.brpop.return_value = (
            "plan-runner:command_results", 
            json.dumps({"success": True, "message": "started"})
        )
        return svc

    @pytest.mark.asyncio
    async def test_transmission_payload_format(self, executor_service):
        """Mock Send - 실제 LLM API 호출(또는 실행 명령 전파) 전 생성되는 Payload 검증"""
        request = RunRequest(
            engine="gemini",
            plan_file="test_plan.md",
            max_cycles=3
        )
        
        captured_payloads = []
        async def mock_lpush(key, payload):
            captured_payloads.append(json.loads(payload))
        
        executor_service.async_redis.lpush = mock_lpush
        
        await executor_service.start_dev_runner(request)
        
        assert len(captured_payloads) == 1
        payload = captured_payloads[0]
        
        # Verify the exact keys and types sent across the wire
        assert payload["action"] == "run"
        assert payload["source"] == "monitor-page-api"
        assert "timestamp" in payload
        assert payload["engine"] == "gemini"
        assert payload["plan_file"] == "test_plan.md"
        assert payload["max_cycles"] == 3
