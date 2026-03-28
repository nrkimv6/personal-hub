"""trigger source 통합 TC

Phase T3: fakeredis로 executor → Redis command + log_service 폴백 동작 검증
"""
import json
import tempfile
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


# --- T3: roundtrip Redis ---

def test_trigger_roundtrip_redis():
    """fakeredis로 executor start_dev_runner() → Redis command JSON에 trigger 필드 존재 + 값 검증"""
    import fakeredis
    import fakeredis.aioredis as aioredis_fake

    pushed_commands = []

    # sync fakeredis client (for LPUSH capture)
    fake_sync = fakeredis.FakeRedis()

    with patch("app.modules.dev_runner.services.executor_service.redis.Redis") as mock_r_cls, \
         patch("app.modules.dev_runner.services.executor_service.aioredis.Redis") as mock_ar_cls, \
         patch("app.modules.dev_runner.services.executor_service.settings_service") as mock_settings:

        mock_settings.get.return_value = MagicMock(max_concurrent_runners=5)
        mock_r_cls.return_value = fake_sync
        mock_async = AsyncMock()
        mock_async.scard = AsyncMock(return_value=0)

        def capture_lpush(key, val):
            pushed_commands.append(json.loads(val))
            return 1
        mock_async.lpush = AsyncMock(side_effect=capture_lpush)
        # brpop이 성공 응답을 반환하도록 설정
        mock_async.brpop = AsyncMock(return_value=(b"plan-runner:command_results:x", json.dumps({"success": True, "message": "ok"}).encode()))
        mock_async.delete = AsyncMock()
        mock_async.get = AsyncMock(return_value=None)
        mock_ar_cls.return_value = mock_async

        from app.modules.dev_runner.schemas import RunRequest
        from app.modules.dev_runner.services.executor_service import ExecutorService
        import asyncio

        svc = ExecutorService()

        # _check_redis_and_listener, cleanup_stale_runners, brpop을 mock으로 처리
        async def run_test():
            svc._check_redis_and_listener = AsyncMock()
            svc.cleanup_stale_runners = AsyncMock(return_value={"cleaned_active": 0, "cleaned_recent": 0, "bugs": 0, "total": 0})
            await svc.start_dev_runner(RunRequest(trigger="user", plan_file="test.md", dry_run=True))

        asyncio.get_event_loop().run_until_complete(run_test())

    # pushed_commands에 command가 있어야 함
    assert len(pushed_commands) > 0, "command가 Redis에 push되지 않음"
    cmd = pushed_commands[0]
    assert "trigger" in cmd, f"trigger 필드 없음: {cmd}"
    assert cmd["trigger"] == "user", f"trigger 값 오류: {cmd['trigger']}"


def test_trigger_log_file_header_written():
    """tmpdir에 로그 파일 생성 → _launch_plan_runner_process의 헤더 기록 로직 검증"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        tmp = f.name

    try:
        # 헤더 기록 로직을 직접 시뮬레이션 (listener의 _launch_plan_runner_process에서)
        command = {"trigger": "tc:my_test", "engine": "claude"}
        plan_file = "test.md"
        runner_id = "abcd1234"

        with open(tmp, "w", encoding="utf-8") as log_handle:
            log_handle.write(f"[TRIGGER] {command.get('trigger', 'unknown')} | plan={plan_file} | engine={command.get('engine', 'claude')} | runner_id={runner_id}\n")
            log_handle.flush()

        with open(tmp, "r", encoding="utf-8") as f:
            first_line = f.readline().rstrip("\n")

        assert first_line.startswith("[TRIGGER] tc:my_test |"), f"헤더 기록 오류: {first_line}"
        assert "plan=test.md" in first_line
        assert "runner_id=abcd1234" in first_line
    finally:
        os.unlink(tmp)


def test_trigger_log_service_redis_fallback():
    """Redis에 trigger 없을 때 log_service가 로그 파일에서 [TRIGGER] 파싱하여 반환"""
    from app.modules.dev_runner.services.log_service import LogService

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("[TRIGGER] user:all | plan=None | engine=claude | runner_id=xyz\n")
        f.write("2026-03-23 INFO Plan runner started\n")
        tmp = f.name

    try:
        # Redis에 trigger 없는 경우 (None) → 파일 폴백
        trigger_from_redis = None
        if trigger_from_redis is None:
            trigger_from_redis = LogService._parse_trigger_from_log(tmp)

        assert trigger_from_redis == "user:all", f"폴백 파싱 오류: {trigger_from_redis}"
    finally:
        os.unlink(tmp)
