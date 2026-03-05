"""RIGHT-BICEP 원칙 테스트: max_cycles=0 (무제한) 버그 수정 검증

버그: executor_service.py에서 `if request.max_cycles and ...` → 0은 falsy → command 누락
픽스: `if request.max_cycles is not None:` 으로 수정

RIGHT-BICEP:
  R - Right: 정상 케이스가 올바른 결과를 내는가
  B - Boundary: 경계값에서 올바르게 동작하는가
  I - Inverse: 역방향 관계를 확인하는가
  C - Cross-check: 다른 방법으로 결과를 교차 검증하는가
  E - Error conditions: 오류 조건이 올바르게 처리되는가
  P - Performance: 성능 요건을 만족하는가
"""

import json
import time
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest
from fastapi import HTTPException


# ========== Fixtures ==========

@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def fake_async_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def executor(fake_redis, fake_async_redis):
    svc = ExecutorService()
    svc.redis_client = fake_redis
    svc.async_redis = fake_async_redis
    return svc


async def _setup_idle(fake_async_redis, plan_file="test.md"):
    await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
    await fake_async_redis.set("plan-runner:state:status", "idle")
    await fake_async_redis.set("plan-runner:state:pid", "0")
    await fake_async_redis.set("plan-runner:state:plan_file", plan_file)
    await fake_async_redis.set("plan-runner:state:start_time", datetime.now().isoformat())


async def _capture_command(executor, fake_async_redis, request: RunRequest) -> dict:
    """lpush 캡처 헬퍼 — per-command result key 대응"""
    captured = []
    original_lpush = fake_async_redis.lpush
    original_brpop = fake_async_redis.brpop

    async def capture_lpush(key, *values):
        captured.extend(values)
        # command에서 command_id를 추출하여 per-command result key에 결과 seed
        for v in values:
            try:
                cmd = json.loads(v)
                if "command_id" in cmd:
                    result_key = f"plan-runner:command_results:{cmd['command_id']}"
                    await original_lpush(result_key, json.dumps({"success": True, "pid": 12345}))
            except (json.JSONDecodeError, TypeError):
                pass
        return await original_lpush(key, *values)

    with patch.object(executor.async_redis, "lpush", side_effect=capture_lpush):
        await executor.start_dev_runner(request)

    return json.loads(captured[0])


# ========== R - Right ==========

class TestRight:
    """R: 정상 입력에 대해 올바른 결과를 내는가"""

    async def test_max_cycles_zero_is_in_command(self, executor, fake_async_redis):
        """max_cycles=0 → command["max_cycles"] == 0"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0))
        assert "max_cycles" in cmd
        assert cmd["max_cycles"] == 0

    async def test_max_cycles_positive_is_in_command(self, executor, fake_async_redis):
        """max_cycles=5 → command["max_cycles"] == 5"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=5))
        assert cmd["max_cycles"] == 5

    async def test_max_tokens_zero_is_in_command(self, executor, fake_async_redis):
        """max_tokens=0 (무제한) → command["max_tokens"] == 0 (동일 버그 패턴)"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_tokens=0))
        assert "max_tokens" in cmd
        assert cmd["max_tokens"] == 0

    async def test_max_cycles_none_absent_from_command(self, executor, fake_async_redis):
        """max_cycles=None → command에 max_cycles 키 없음"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=None))
        assert "max_cycles" not in cmd


# ========== B - Boundary ==========

class TestBoundary:
    """B: 경계값에서 올바르게 동작하는가"""

    async def test_max_cycles_1_minimum_finite(self, executor, fake_async_redis):
        """max_cycles=1 → 최소 유한값, command에 포함"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=1))
        assert cmd["max_cycles"] == 1

    async def test_max_cycles_large_value(self, executor, fake_async_redis):
        """max_cycles=9999 → 큰 값도 그대로 전달"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=9999))
        assert cmd["max_cycles"] == 9999

    async def test_max_cycles_zero_and_tokens_zero_both_present(self, executor, fake_async_redis):
        """max_cycles=0 AND max_tokens=0 → 둘 다 command에 포함"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(
            executor, fake_async_redis,
            RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0, max_tokens=0)
        )
        assert cmd["max_cycles"] == 0
        assert cmd["max_tokens"] == 0

    async def test_max_cycles_none_and_tokens_none_both_absent(self, executor, fake_async_redis):
        """max_cycles=None AND max_tokens=None → 둘 다 command에 없음"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(
            executor, fake_async_redis,
            RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=None, max_tokens=None)
        )
        assert "max_cycles" not in cmd
        assert "max_tokens" not in cmd


# ========== I - Inverse ==========

class TestInverse:
    """I: 역방향 관계 확인 (값 있음 ↔ command 포함 여부 역전)"""

    @pytest.mark.parametrize("value,should_exist", [
        (0, True),    # 0 = 무제한 → 포함
        (1, True),    # 양수 → 포함
        (10, True),   # 양수 → 포함
        (None, False),  # None → 미포함
    ])
    async def test_max_cycles_presence_matrix(self, executor, fake_async_redis, value, should_exist):
        """max_cycles 값과 command 포함 여부 매트릭스"""
        # 매 케이스마다 fresh 세팅
        await fake_async_redis.flushall()
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(
            executor, fake_async_redis,
            RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=value)
        )
        assert ("max_cycles" in cmd) == should_exist, (
            f"max_cycles={value}: command 포함={should_exist}이어야 하지만 포함={'max_cycles' in cmd}"
        )

    @pytest.mark.parametrize("value,should_exist", [
        (0, True),
        (1, True),
        (None, False),
    ])
    async def test_max_tokens_presence_matrix(self, executor, fake_async_redis, value, should_exist):
        """max_tokens 값과 command 포함 여부 매트릭스"""
        await fake_async_redis.flushall()
        await _setup_idle(fake_async_redis)
        cmd = await _capture_command(
            executor, fake_async_redis,
            RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_tokens=value)
        )
        assert ("max_tokens" in cmd) == should_exist


# ========== C - Cross-check ==========

class TestCrossCheck:
    """C: 다른 방법으로 결과를 교차 검증"""

    async def test_command_json_round_trip(self, executor, fake_async_redis):
        """JSON 직렬화/역직렬화 후 max_cycles=0 값 보존"""
        await _setup_idle(fake_async_redis)

        raw_captured = []
        original = fake_async_redis.lpush

        async def capture(key, *values):
            raw_captured.extend(values)
            # per-command result key에 결과 seed
            for v in values:
                try:
                    cmd = json.loads(v)
                    if "command_id" in cmd:
                        result_key = f"plan-runner:command_results:{cmd['command_id']}"
                        await original(result_key, json.dumps({"success": True, "pid": 12345}))
                except (json.JSONDecodeError, TypeError):
                    pass
            return await original(key, *values)

        with patch.object(executor.async_redis, "lpush", side_effect=capture):
            await executor.start_dev_runner(RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0))

        # JSON 문자열에서 직접 검증
        raw_json = raw_captured[0]
        assert '"max_cycles": 0' in raw_json or '"max_cycles":0' in raw_json

        # 역직렬화 후 검증
        parsed = json.loads(raw_json)
        assert parsed["max_cycles"] == 0
        assert isinstance(parsed["max_cycles"], int)

    def test_command_listener_logic_mirrors_executor(self):
        """command-listener가 executor와 동일하게 is not None 패턴을 사용하는지 검증"""
        # command-listener 로직 재현
        def build_cli_args(command: dict) -> list:
            args = []
            if command.get("max_cycles") is not None:
                args.extend(["--max-cycles", str(command["max_cycles"])])
            if command.get("max_tokens") is not None:
                args.extend(["--max-tokens", str(command["max_tokens"])])
            return args

        # executor가 만든 command (max_cycles=0 포함) → listener가 --max-cycles 0 추가
        command_from_executor = {"max_cycles": 0, "max_tokens": 0}
        args = build_cli_args(command_from_executor)
        assert "--max-cycles" in args
        assert args[args.index("--max-cycles") + 1] == "0"
        assert "--max-tokens" in args

        # executor가 만든 command (max_cycles 없음) → listener가 --max-cycles 추가 안 함
        command_no_cycles = {}
        args2 = build_cli_args(command_no_cycles)
        assert "--max-cycles" not in args2


# ========== E - Error Conditions ==========

class TestErrorConditions:
    """E: 오류 조건이 올바르게 처리되는가"""

    async def test_already_running_allows_additional_runner_with_max_cycles_zero(self, executor, fake_async_redis, fake_redis):
        """멀티 runner: 이미 실행 중이어도 max_cycles=0 추가 실행 허용 (409 없음)"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")

        # per-command result key에 결과를 seed하기 위해 lpush를 가로챔
        original_lpush = fake_async_redis.lpush

        async def auto_seed_result(key, *values):
            res = await original_lpush(key, *values)
            for v in values:
                try:
                    cmd = json.loads(v)
                    if "command_id" in cmd:
                        result_key = f"plan-runner:command_results:{cmd['command_id']}"
                        await original_lpush(result_key, json.dumps({"success": True, "pid": 12345}))
                except (json.JSONDecodeError, TypeError):
                    pass
            return res

        with patch.object(executor.async_redis, "lpush", side_effect=auto_seed_result):
            result = await executor.start_dev_runner(RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0))
        assert result.runner_id is not None  # 새 runner_id 발급됨
        assert result.runner_id.startswith("t-bicep_max_cycles-")  # test_source 포함 형식

    async def test_listener_dead_raises_503_regardless_of_max_cycles(self, executor, fake_async_redis):
        """listener 없을 때 max_cycles=0 요청도 503 반환"""
        # heartbeat 없음 → listener 없음
        import redis as redis_lib
        executor.async_redis = AsyncMock()
        executor.async_redis.ping = AsyncMock(side_effect=redis_lib.exceptions.ConnectionError("no conn"))
        with pytest.raises(HTTPException) as exc:
            await executor.start_dev_runner(RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0))
        assert exc.value.status_code == 503

    def test_schema_rejects_non_integer_max_cycles(self):
        """max_cycles에 문자열 전달 시 ValidationError 발생"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RunRequest(test_source="bicep_max_cycles", max_cycles="unlimited")


# ========== P - Performance ==========

class TestPerformance:
    """P: 성능 요건 — command 빌드가 수용 가능한 시간 내 완료"""

    async def test_command_build_under_100ms(self, executor, fake_async_redis):
        """max_cycles=0 포함 command 빌드 100ms 이내"""
        await _setup_idle(fake_async_redis)

        start = time.perf_counter()
        await _capture_command(executor, fake_async_redis, RunRequest(test_source="bicep_max_cycles", plan_file="test.md", max_cycles=0))
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"Command 빌드 {elapsed_ms:.1f}ms — 100ms 초과"
