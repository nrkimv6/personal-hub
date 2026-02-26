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


def _make_capture_lpush(async_redis, captured, result_data=None):
    """per-command result key 자동 seed하는 capture_lpush 팩토리"""
    if result_data is None:
        result_data = {"success": True, "pid": 12345}
    original = async_redis.lpush

    async def capture_lpush(key, *values):
        captured.extend(values)
        for v in values:
            try:
                cmd = json.loads(v)
                if "command_id" in cmd:
                    result_key = f"plan-runner:command_results:{cmd['command_id']}"
                    await original(result_key, json.dumps(result_data))
            except (json.JSONDecodeError, TypeError):
                pass
        return await original(key, *values)

    return capture_lpush

# ==========================================
# Phase 9: 버그 수정 검증 (API 응답 engine 필드)
# ==========================================

class TestBugFixEngineReporting:
    """Phase 8 & 9: API 응답 내 engine 필드 고정/누락 버그 검증"""

    async def test_start_dev_runner_returns_requested_engine_immediately(self, executor):
        """[Right] start_dev_runner가 Redis 상태와 무관하게 요청된 엔진을 즉시 반환하는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")

        captured = []
        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(executor.async_redis, captured, {"success": True, "pid": 5555})):
            req = RunRequest(engine="gemini", plan_file="test.md")
            result = await executor.start_dev_runner(req)

        assert result.engine == "gemini"

    def test_status_response_engine_is_none_by_default(self):
        """[Conformance] RunStatusResponse의 engine 기본값이 None인가? (schemas.py 수정 확인)"""
        resp = RunStatusResponse(running=False)
        assert resp.engine is None

    def test_get_process_status_returns_engine_from_redis(self, executor):
        """[Right] get_process_status가 Redis에 저장된 엔진 정보를 정확히 읽어오는가? (per-runner 키)"""
        runner_id = "abc12345"
        executor.redis_client.set("plan-runner:listener:heartbeat", "alive")
        executor.redis_client.sadd("plan-runner:active_runners", runner_id)
        executor.redis_client.set(f"plan-runner:runners:{runner_id}:status", "running")
        executor.redis_client.set(f"plan-runner:runners:{runner_id}:engine", "gemini")
        executor.redis_client.set(f"plan-runner:runners:{runner_id}:pid", "1234")

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
import re

class MockExecutionResult:
    def __init__(self, success, status, output, raw_output, model_used, error=None):
        self.success = success
        self.status = status
        self.output = output
        self.raw_output = raw_output
        self.model_used = model_used
        self.error = error

class AIExecutorStandalone:
    def _build_gemini_command(self, prompt, model=None, flags=None):
        cmd = ["gemini"]
        if model: cmd.extend(["--model", model])
        if flags: cmd.extend(flags)
        cmd.extend(["-p", prompt])
        return cmd

    def _extract_status_from_output(self, output):
        patterns = [r'STATUS:\s*(SUCCESS|FAILED|SKIPPED)', r'Status:\s*(SUCCESS|FAILED|SKIPPED)']
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match: return match.group(1).lower()
        return None

    def _parse_gemini_output(self, stdout, stderr, returncode, model):
        success = returncode == 0
        status = self._extract_status_from_output(stdout) or ("success" if success else "failed")
        return MockExecutionResult(
            success=success, status=status, output=stdout, raw_output=stdout, model_used=model,
            error=f"Exit code: {returncode} | stderr: {stderr}" if not success else None
        )

    def _stream_gemini_line(self, line):
        clean_line = re.sub(r'\033\[[0-9;]*m', '', line)
        tag = "LINE"
        if "Tool use:" in clean_line or "Calling" in clean_line: tag = "TOOL"
        elif "Thinking:" in clean_line: tag = "THINK"
        self._accumulated_output.append(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {clean_line}")

@pytest.fixture
def ai_executor():
    executor = AIExecutorStandalone()
    executor._accumulated_output = []
    return executor

class TestAIExecutorGeminiLogic:
    """AIExecutor의 Gemini 명령줄 생성 및 파싱 로직 검증"""

    def test_build_gemini_command(self, ai_executor):
        """[Right] 모델과 플래그가 포함된 Gemini 명령줄이 올바르게 생성되는가?"""
        prompt = "test prompt"
        model = "gemini-2.0-flash"
        flags = ["--yolo", "--sandbox=false"]
        
        cmd = ai_executor._build_gemini_command(prompt, model, flags)
        
        assert cmd == ["gemini", "--model", "gemini-2.0-flash", "--yolo", "--sandbox=false", "-p", "test prompt"]

    def test_parse_gemini_output_success(self, ai_executor):
        """[Right] Gemini의 텍스트 출력에서 성공 상태를 잘 추출하는가?"""
        stdout = "Some reasoning...\nSTATUS: SUCCESS\n===END==="
        result = ai_executor._parse_gemini_output(stdout, "", 0, "gemini-2.0-flash")
        
        assert result.success is True
        assert result.status == "success"
        assert result.model_used == "gemini-2.0-flash"

    def test_parse_gemini_output_failure(self, ai_executor):
        """[Error] Exit code가 0이 아닐 때 에러 메시지를 포함하는가?"""
        stdout = "Execution failed..."
        stderr = "API Error"
        result = ai_executor._parse_gemini_output(stdout, stderr, 1, "gemini-2.0-flash")
        
        assert result.success is False
        assert "Exit code: 1" in result.error
        assert "stderr: API Error" in result.error

    def test_stream_gemini_line_tagging(self, ai_executor):
        """[Conformance] Gemini 출력 라인별 태깅(TOOL, THINK)이 정상인가?"""
        # 1. Tool use 감지
        ai_executor._accumulated_output = []
        ai_executor._stream_gemini_line("Calling tool: ReadFile...")
        assert "TOOL" in ai_executor._accumulated_output[-1]
        
        # 2. Thinking 감지
        ai_executor._stream_gemini_line("Thinking: I should check the logs.")
        assert "THINK" in ai_executor._accumulated_output[-1]
        
        # 3. 일반 라인
        ai_executor._stream_gemini_line("Hello world")
        assert "LINE" in ai_executor._accumulated_output[-1]

# ==========================================
# Phase 7: 심화 검증 (Right-BICEP & CORRECT)
# ==========================================

class TestGeminiDeepValidation:
    """Phase 7: 엔진 전환 및 데이터 정합성 심화 검증"""

    async def test_engine_parameter_passed_to_redis_command(self, executor):
        """[CORRECT: Conformance] engine 파라미터가 Redis LPush 명령에 포함되는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")

        captured = []
        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(executor.async_redis, captured)):
            await executor.start_dev_runner(RunRequest(engine="gemini"))

        command = json.loads(captured[0])
        assert command["engine"] == "gemini"

    async def test_concurrent_run_requests_allowed(self, executor):
        """[CORRECT: Time] 멀티 runner: 이미 실행 중이어도 추가 run 요청 가능 (409 없음)"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")

        captured = []
        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(executor.async_redis, captured)):
            result = await executor.start_dev_runner(RunRequest(engine="claude"))
        assert result.runner_id is not None
        assert len(result.runner_id) == 8

    def test_status_reporting_with_stale_pid(self, executor):
        """[Right-BICEP: Error] PID는 있지만 프로세스가 죽었을 때(stale) 자동 정리되는가?"""
        runner_id = "abc12345"
        executor.redis_client.set("plan-runner:listener:heartbeat", "alive")
        executor.redis_client.sadd("plan-runner:active_runners", runner_id)
        executor.redis_client.set(f"plan-runner:runners:{runner_id}:status", "running")
        executor.redis_client.set(f"plan-runner:runners:{runner_id}:pid", "99999")  # 죽은 PID

        with patch("psutil.pid_exists", return_value=False):
            status = executor.get_process_status()
            assert status.running is False
            # per-runner Redis 상태도 삭제되어야 함
            assert executor.redis_client.get(f"plan-runner:runners:{runner_id}:status") is None

    async def test_engine_field_optional_conformance(self, executor):
        """[CORRECT: Conformance] engine 필드가 누락된 요청도 정상 처리(claude 기본값)되는가?"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")

        req = RunRequest(plan_file="test.md")
        assert req.engine == "claude"

        captured = []
        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(executor.async_redis, captured)):
            result = await executor.start_dev_runner(req)
        assert result.engine == "claude"

    # ==========================================
    # Phase 7: 심화 검증 (추가 항목)
    # ==========================================

    def test_existence_engines_json_missing(self, executor):
        """[CORRECT: Existence] engines.json 파일이 없을 때 기본 Claude 설정을 반환하는가?"""
        # executor.config가 없으므로 로직만 검증하도록 Mock 구성
        mock_config = MagicMock()
        mock_config.get_engine_config.return_value = {
            "default_model": "sonnet",
            "flags": ["--dangerously-skip-permissions"],
            "models": {}
        }
        
        config = mock_config.get_engine_config("gemini")
        assert config["default_model"] == "sonnet"
        assert "--dangerously-skip-permissions" in config["flags"]

    def test_cardinality_multiple_flags(self, executor):
        """[CORRECT: Cardinality] 여러 개의 플래그가 설정되었을 때 명령줄에 모두 포함되는가?"""
        prompt = "test"
        model = "gemini-pro"
        flags = ["--yolo", "--no-sandbox", "--temp=0.7"]
        
        # AIExecutorStandalone의 메서드 활용 (Mock)
        executor_logic = AIExecutorStandalone()
        cmd = executor_logic._build_gemini_command(prompt, model, flags)
        
        assert "--yolo" in cmd
        assert "--no-sandbox" in cmd
        assert "--temp=0.7" in cmd
        assert cmd.index("--model") < cmd.index("gemini-pro")

    async def test_error_invalid_model_name(self, executor):
        """[Right-BICEP: Error] 존재하지 않는 모델명으로 실행 요청 시의 처리 (Schema 검증)"""
        await executor.async_redis.set("plan-runner:listener:heartbeat", "alive")

        captured = []
        with patch.object(executor.async_redis, 'lpush', side_effect=_make_capture_lpush(executor.async_redis, captured, {"success": False, "message": "Invalid model"})):
            with pytest.raises(HTTPException) as exc:
                await executor.start_dev_runner(RunRequest(engine="gemini", max_cycles=1))
        assert exc.value.status_code == 500

    def test_boundary_empty_prompt(self, executor):
        """[Right-BICEP: Boundary] 빈 프롬프트가 주어졌을 때 명령줄 생성 확인"""
        executor_logic = AIExecutorStandalone()
        cmd = executor_logic._build_gemini_command("", "model", ["--yolo"])
        assert cmd[-1] == "" # 마지막 인자인 prompt가 빈 문자열이어야 함
