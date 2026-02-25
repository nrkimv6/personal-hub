import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
import fakeredis
import fakeredis.aioredis
from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest, RunStatusResponse
from fastapi import HTTPException

@pytest.fixture
def executor():
    service = ExecutorService()
    service.redis_client = fakeredis.FakeRedis(decode_responses=True)
    service.async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return service

# ==========================================
# Phase 9: 버그 수정 검증 (API 응답 engine 필드)
# ==========================================

class TestBugFixEngineReporting:
    """Phase 8 & 9: API 응답 내 engine 필드 고정/누락 버그 검증"""

    async def test_start_dev_runner_returns_requested_engine_immediately(self, executor):
        """[Right] start_dev_runner가 Redis 상태와 무관하게 요청된 엔진을 즉시 반환하는가?"""
        # Listener 성공 응답 시뮬레이션
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")
        result_data = {"success": True, "pid": 5555}
        await executor.async_redis.rpush("plan-runner:command_results", json.dumps(result_data))
        
        req = RunRequest(engine="gemini", plan_file="test.md")
        result = await executor.start_dev_runner(req)
        
        # 반환된 객체의 engine이 'gemini'여야 함 (버그 수정 확인)
        assert result.engine == "gemini"

    def test_status_response_engine_is_none_by_default(self):
        """[Conformance] RunStatusResponse의 engine 기본값이 None인가? (schemas.py 수정 확인)"""
        resp = RunStatusResponse(running=False)
        assert resp.engine is None

    def test_get_process_status_returns_engine_from_redis(self, executor):
        """[Right] get_process_status가 Redis에 저장된 엔진 정보를 정확히 읽어오는가?"""
        executor.redis_client.set("plan-runner:listener:heartbeat", "alive")
        executor.redis_client.set("plan-runner:state:status", "running")
        executor.redis_client.set("plan-runner:state:engine", "gemini")
        executor.redis_client.set("plan-runner:state:pid", "1234")
        
        with patch("psutil.pid_exists", return_value=True):
            status = executor.get_process_status()
            assert status.engine == "gemini"

    def test_get_process_status_fallback_to_claude(self, executor):
        """[Error] Redis에 engine 정보가 없을 때 claude로 폴백하는가?"""
        executor.redis_client.set("plan-runner:listener:heartbeat", "alive")
        executor.redis_client.set("plan-runner:state:status", "idle")
        # engine key 없음
        
        status = executor.get_process_status()
        assert status.engine == "claude"

# ==========================================
# AIExecutor 내부 로직 검증 (Gemini 특화)
# ==========================================

class TestAIExecutorGeminiLogic:
    """AIExecutor의 Gemini 명령줄 생성 및 파싱 로직 검증"""

    def test_build_gemini_command(self, executor):
        """[Right] 모델과 플래그가 포함된 Gemini 명령줄이 올바르게 생성되는가?"""
        prompt = "test prompt"
        model = "gemini-2.0-flash"
        flags = ["--yolo", "--sandbox=false"]
        
        cmd = executor._build_gemini_command(prompt, model, flags)
        
        assert cmd == ["gemini", "--model", "gemini-2.0-flash", "--yolo", "--sandbox=false", "-p", "test prompt"]

    def test_parse_gemini_output_success(self, executor):
        """[Right] Gemini의 텍스트 출력에서 성공 상태를 잘 추출하는가?"""
        stdout = "Some reasoning...\nSTATUS: SUCCESS\n===END==="
        result = executor._parse_gemini_output(stdout, "", 0, "gemini-2.0-flash")
        
        assert result.success is True
        assert result.status == "success"
        assert result.model_used == "gemini-2.0-flash"

    def test_parse_gemini_output_failure(self, executor):
        """[Error] Exit code가 0이 아닐 때 에러 메시지를 포함하는가?"""
        stdout = "Execution failed..."
        stderr = "API Error"
        result = executor._parse_gemini_output(stdout, stderr, 1, "gemini-2.0-flash")
        
        assert result.success is False
        assert "Exit code: 1" in result.error
        assert "stderr: API Error" in result.error

    def test_stream_gemini_line_tagging(self, executor):
        """[Conformance] Gemini 출력 라인별 태깅(TOOL, THINK)이 정상인가?"""
        # 1. Tool use 감지
        executor._accumulated_output = []
        executor._stream_gemini_line("Calling tool: ReadFile...")
        assert "TOOL" in executor._accumulated_output[-1]
        
        # 2. Thinking 감지
        executor._stream_gemini_line("Thinking: I should check the logs.")
        assert "THINK" in executor._accumulated_output[-1]
        
        # 3. 일반 라인
        executor._stream_gemini_line("Hello world")
        assert "LINE" in executor._accumulated_output[-1]

# ==========================================
# Phase 7: 심화 검증 (Right-BICEP & CORRECT)
# ==========================================

class TestGeminiDeepValidation:
    """Phase 7: 엔진 전환 및 데이터 정합성 심화 검증"""

    async def test_engine_parameter_passed_to_redis_command(self, executor):
        """[CORRECT: Conformance] engine 파라미터가 Redis LPush 명령에 포함되는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")
        
        captured_command = None
        original_lpush = executor.async_redis.lpush
        async def mock_lpush(key, val):
            nonlocal captured_command
            if key == "plan-runner:commands":
                captured_command = json.loads(val)
            return await original_lpush(key, val)

        with patch.object(executor.async_redis, 'lpush', side_effect=mock_lpush):
            # listener 응답용 결과 미리 삽입
            await executor.async_redis.rpush("plan-runner:command_results", json.dumps({"success": True}))
            await executor.start_dev_runner(RunRequest(engine="gemini"))

        assert captured_command is not None
        assert captured_command["engine"] == "gemini"

    async def test_concurrent_run_requests_conflict(self, executor):
        """[CORRECT: Time] 이미 실행 중일 때 새로운 run 요청 시 409 에러가 발생하는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")
        await executor.async_redis.set("plan-runner:state:status", "running")
        
        with pytest.raises(HTTPException) as exc:
            await executor.start_dev_runner(RunRequest(engine="claude"))
        assert exc.value.status_code == 409

    def test_status_reporting_with_stale_pid(self, executor):
        """[Right-BICEP: Error] PID는 있지만 프로세스가 죽었을 때(stale) 자동 정리되는가?"""
        executor.redis_client.set("plan-runner:listener:heartbeat", "alive")
        executor.redis_client.set("plan-runner:state:status", "running")
        executor.redis_client.set("plan-runner:state:pid", "99999") # 존재하지 않을 법한 PID
        
        with patch("psutil.pid_exists", return_value=False):
            status = executor.get_process_status()
            assert status.running is False
            # Redis 상태도 삭제되어야 함
            assert executor.redis_client.get("plan-runner:state:status") is None

    async def test_engine_field_optional_conformance(self, executor):
        """[CORRECT: Conformance] engine 필드가 누락된 요청도 정상 처리(claude 기본값)되는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")
        # listener 응답용 결과 미리 삽입
        await executor.async_redis.rpush("plan-runner:command_results", json.dumps({"success": True}))
        
        # engine 필드 없이 요청
        req = RunRequest(plan_file="test.md")
        assert req.engine == "claude" # Pydantic default
        
        result = await executor.start_dev_runner(req)
        assert result.engine == "claude"
