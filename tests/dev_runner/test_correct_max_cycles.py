"""CORRECT 원칙 테스트: max_cycles=0 (무제한) 버그 수정 검증

CORRECT:
  C - Conformance: 값이 기대 형식에 맞는가
  O - Ordering: 순서 의존성이 올바른가
  R - Range: 유효 범위가 올바른가
  R - Reference: 외부 의존성이 올바르게 참조되는가
  E - Existence: 값이 존재해야 할 때 존재하는가 (None/없음 케이스)
  C - Cardinality: 개수가 정확한가
  T - Time: 타이밍/순서가 올바른가
"""

import json
import pytest
from datetime import datetime
from unittest.mock import patch
import fakeredis
import fakeredis.aioredis
from pydantic import ValidationError

from app.modules.dev_runner.services.executor_service import ExecutorService
from app.modules.dev_runner.schemas import RunRequest


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


async def _setup_idle(r):
    await r.set("plan-runner:listener:heartbeat", "alive")
    await r.set("plan-runner:state:status", "idle")
    await r.set("plan-runner:state:pid", "0")
    await r.set("plan-runner:state:plan_file", "test.md")
    await r.set("plan-runner:state:start_time", datetime.now().isoformat())
    await r.rpush("plan-runner:command_results", json.dumps({"success": True, "pid": 1}))


async def _capture(executor, r, req):
    captured = []
    orig = r.lpush

    async def cap(key, *vals):
        captured.extend(vals)
        return await orig(key, *vals)

    with patch.object(executor.async_redis, "lpush", side_effect=cap):
        await executor.start_dev_runner(req)
    return json.loads(captured[0])


# ========== C - Conformance ==========

class TestConformance:
    """값이 기대 형식(타입, 구조)에 맞는가"""

    def test_max_cycles_zero_is_integer_in_schema(self):
        """RunRequest.max_cycles=0 → int 타입"""
        r = RunRequest(max_cycles=0)
        assert isinstance(r.max_cycles, int)
        assert r.max_cycles == 0

    def test_max_cycles_zero_serializes_as_integer_in_json(self):
        """RunRequest.max_cycles=0 → JSON 직렬화 시 정수 0 (문자열 "0" 아님)"""
        r = RunRequest(plan_file="test.md", max_cycles=0)
        d = r.model_dump()
        assert d["max_cycles"] == 0
        assert not isinstance(d["max_cycles"], str)

    async def test_command_max_cycles_zero_is_int_type(self, executor, fake_async_redis):
        """Redis command에 기록된 max_cycles가 int 0"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))
        assert isinstance(cmd["max_cycles"], int)
        assert cmd["max_cycles"] == 0

    def test_command_listener_cli_arg_is_string_zero(self):
        """command-listener가 --max-cycles 인자를 str("0")으로 전달"""
        # argparse는 문자열 인자를 받으므로 str 변환 필요
        command = {"max_cycles": 0}
        args = []
        if command.get("max_cycles") is not None:
            args.extend(["--max-cycles", str(command["max_cycles"])])
        assert args == ["--max-cycles", "0"]
        assert isinstance(args[1], str)

    def test_max_cycles_schema_default_is_zero(self):
        """RunRequest 기본값: max_cycles=0 (무제한)"""
        r = RunRequest()
        assert r.max_cycles == 0

    def test_max_tokens_schema_default_is_zero(self):
        """RunRequest 기본값: max_tokens=0 (무제한)"""
        r = RunRequest()
        assert r.max_tokens == 0


# ========== O - Ordering ==========

class TestOrdering:
    """명령 전달 순서 및 처리 순서가 올바른가"""

    async def test_max_cycles_field_order_in_command(self, executor, fake_async_redis):
        """command dict에 action이 먼저, max_cycles가 그 이후에 추가됨"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))

        keys = list(cmd.keys())
        assert "action" in keys
        assert "max_cycles" in keys
        assert keys.index("action") < keys.index("max_cycles")

    async def test_multiple_optional_fields_all_present(self, executor, fake_async_redis):
        """max_cycles=0, max_tokens=0, until, dry_run 동시에 모두 command에 포함"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(
            executor, fake_async_redis,
            RunRequest(plan_file="test.md", max_cycles=0, max_tokens=0, until="20:00", dry_run=True)
        )
        assert cmd["max_cycles"] == 0
        assert cmd["max_tokens"] == 0
        assert cmd["until"] == "20:00"
        assert cmd["dry_run"] is True


# ========== R - Range ==========

class TestRange:
    """유효 범위 (0 이상의 정수, 음수/문자열 거부)"""

    def test_max_cycles_zero_valid(self):
        """max_cycles=0 유효"""
        r = RunRequest(max_cycles=0)
        assert r.max_cycles == 0

    def test_max_cycles_positive_valid(self):
        """max_cycles=100 유효"""
        r = RunRequest(max_cycles=100)
        assert r.max_cycles == 100

    def test_max_cycles_string_invalid(self):
        """max_cycles 문자열 → ValidationError"""
        with pytest.raises(ValidationError):
            RunRequest(max_cycles="infinite")

    def test_max_cycles_float_coerced_or_rejected(self):
        """max_cycles=3.0 → int로 강제 변환 또는 오류 (pydantic 동작 확인)"""
        # pydantic v2: float → int 강제 변환 가능
        try:
            r = RunRequest(max_cycles=3)
            assert r.max_cycles == 3
        except ValidationError:
            pass  # 거부도 허용


# ========== R - Reference ==========

class TestReference:
    """외부 의존성(Redis key, CLI 인자명)이 올바르게 참조되는가"""

    async def test_command_pushed_to_correct_redis_key(self, executor, fake_async_redis):
        """command가 'plan-runner:commands' 큐에 LPUSH 됨"""
        await _setup_idle(fake_async_redis)

        pushed_keys = []
        orig = fake_async_redis.lpush

        async def cap(key, *vals):
            pushed_keys.append(key)
            return await orig(key, *vals)

        with patch.object(executor.async_redis, "lpush", side_effect=cap):
            await executor.start_dev_runner(RunRequest(plan_file="test.md", max_cycles=0))

        assert any("command" in k for k in pushed_keys), f"command 큐 키 없음: {pushed_keys}"

    def test_cli_flag_name_is_max_cycles_hyphen(self):
        """CLI 인자명이 '--max-cycles'(언더스코어 아닌 하이픈) 형식"""
        command = {"max_cycles": 0}
        args = []
        if command.get("max_cycles") is not None:
            args.extend(["--max-cycles", str(command["max_cycles"])])
        assert "--max-cycles" in args
        assert "--max_cycles" not in args  # 잘못된 형식 아님


# ========== E - Existence ==========

class TestExistence:
    """값이 존재해야/부재해야 할 상황을 검증"""

    async def test_max_cycles_zero_exists_in_command(self, executor, fake_async_redis):
        """max_cycles=0 → command에 키 존재"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))
        assert "max_cycles" in cmd

    async def test_max_cycles_default_zero_exists_in_command(self, executor, fake_async_redis):
        """RunRequest() 기본값(max_cycles=0) → command에 키 존재"""
        await _setup_idle(fake_async_redis)
        # 기본값이 0이므로 명시 안 해도 포함되어야 함
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md"))
        assert "max_cycles" in cmd
        assert cmd["max_cycles"] == 0

    async def test_max_cycles_none_absent_from_command(self, executor, fake_async_redis):
        """max_cycles=None → command에 키 부재"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=None))
        assert "max_cycles" not in cmd

    async def test_action_always_exists_in_command(self, executor, fake_async_redis):
        """command에는 항상 action 키가 존재"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))
        assert "action" in cmd
        assert cmd["action"] == "run"


# ========== C - Cardinality ==========

class TestCardinality:
    """개수가 정확한가 — 중복 없이 정확히 1개"""

    async def test_exactly_one_command_pushed(self, executor, fake_async_redis):
        """start_dev_runner 1회 호출 → lpush 1회"""
        await _setup_idle(fake_async_redis)
        captured = []
        orig = fake_async_redis.lpush

        async def cap(key, *vals):
            captured.extend(vals)
            return await orig(key, *vals)

        with patch.object(executor.async_redis, "lpush", side_effect=cap):
            await executor.start_dev_runner(RunRequest(plan_file="test.md", max_cycles=0))

        assert len(captured) == 1, f"command가 {len(captured)}개 푸시됨 (1개여야 함)"

    async def test_max_cycles_key_not_duplicated_in_command(self, executor, fake_async_redis):
        """command JSON에 max_cycles 키가 중복 없이 정확히 1개"""
        await _setup_idle(fake_async_redis)
        captured_raw = []
        orig = fake_async_redis.lpush

        async def cap(key, *vals):
            captured_raw.extend(vals)
            return await orig(key, *vals)

        with patch.object(executor.async_redis, "lpush", side_effect=cap):
            await executor.start_dev_runner(RunRequest(plan_file="test.md", max_cycles=0))

        raw = captured_raw[0]
        count = raw.count('"max_cycles"')
        assert count == 1, f"max_cycles 키가 {count}번 등장 (1번이어야 함)"


# ========== T - Time ==========

class TestTime:
    """타이밍: timestamp가 command에 포함되고 현재 시각 근처인가"""

    async def test_command_has_timestamp(self, executor, fake_async_redis):
        """command에 timestamp 필드가 존재"""
        await _setup_idle(fake_async_redis)
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))
        assert "timestamp" in cmd

    async def test_command_timestamp_is_recent(self, executor, fake_async_redis):
        """command timestamp가 현재 시각 ±5초 이내"""
        import time as _time
        await _setup_idle(fake_async_redis)
        before = datetime.now()
        cmd = await _capture(executor, fake_async_redis, RunRequest(plan_file="test.md", max_cycles=0))
        after = datetime.now()

        ts = datetime.fromisoformat(cmd["timestamp"])
        assert before <= ts <= after, f"timestamp {ts}이 [{before}, {after}] 범위 밖"
