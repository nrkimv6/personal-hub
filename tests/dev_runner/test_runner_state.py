"""RunnerState 단위 TC"""

import importlib
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta
import pytest
import fakeredis.aioredis as fake_aioredis
from unittest.mock import AsyncMock, patch

from app.modules.dev_runner.services.redis_connection import (
    RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY
)
from app.modules.dev_runner.services.runner_state import RunnerState


def runner_key(rid, suffix):
    return f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}"


def make_state(fake_r=None, is_pid_alive_fn=None, force_cleanup_fn=None):
    if fake_r is None:
        fake_r = AsyncMock()
    state = RunnerState(fake_r, runner_key, is_pid_alive_fn, force_cleanup_fn)
    return state


class TestIsPidAlive:
    def test_runner_state_R_is_pid_alive(self):
        """R(Right): 현재 프로세스 PID → True"""
        state = make_state()
        assert state._is_pid_alive(os.getpid()) is True

    def test_runner_state_B_is_pid_dead(self):
        """B(Boundary): 존재하지 않는 PID → False"""
        state = make_state()
        # PID 99999는 거의 없음
        assert state._is_pid_alive(99999) is False


class TestCorrectPidState:
    @pytest.mark.asyncio
    async def test_runner_state_R_correct_pid_running_alive(self):
        """R(Right): status=running + PID alive → (True, '123')"""
        state = make_state(is_pid_alive_fn=lambda p: True)
        result = await state._correct_pid_state("rid1", "running", "123", caller="test")
        assert result == (True, "123")

    @pytest.mark.asyncio
    async def test_runner_state_E_correct_pid_running_dead(self):
        """E(Error): status=running + PID dead → _force_cleanup_fn 호출 + (False, None)"""
        cleanup_mock = AsyncMock()
        state = make_state(
            is_pid_alive_fn=lambda p: False,
            force_cleanup_fn=cleanup_mock
        )
        result = await state._correct_pid_state("rid2", "running", "1234", caller="test")
        assert result == (False, None)
        cleanup_mock.assert_called_once_with("rid2")

    @pytest.mark.asyncio
    async def test_runner_state_R_no_pid(self):
        """B(Boundary): pid_str=None → _is_pid_alive 불리지 않음"""
        called = []
        state = make_state(is_pid_alive_fn=lambda p: called.append(p) or True)
        result_running = await state._correct_pid_state("r", "running", None)
        result_stopped = await state._correct_pid_state("r", "stopped", None)
        assert result_running == (True, None)
        assert result_stopped == (False, None)
        assert called == []


class TestDismissRunner:
    @pytest.mark.asyncio
    async def test_runner_state_R_dismiss_runner(self):
        """R(Right): 키 세팅 후 dismiss → zrem/srem/delete 호출 + True 반환"""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        await fake_r.zadd(RECENT_RUNNERS_KEY, {"r1": 1000})
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, "r1")
        await fake_r.set(runner_key("r1", "status"), "stopped")

        state = make_state(fake_r)
        result = await state.dismiss_runner("r1")

        assert result is True
        assert not await fake_r.zscore(RECENT_RUNNERS_KEY, "r1")
        assert not await fake_r.sismember(ACTIVE_RUNNERS_KEY, "r1")

    @pytest.mark.asyncio
    async def test_runner_state_B_dismiss_nonexistent(self):
        """B(Boundary): 키 없는 runner dismiss → 예외 없이 True"""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        state = make_state(fake_r)
        result = await state.dismiss_runner("nonexist_runner")
        assert result is True


class TestCleanupStaleRunners:
    @pytest.mark.asyncio
    async def test_cleanup_stale_auto_history_archived_R(self, tmp_path):
        """_auto* plan은 docs/history 파일이 있으면 archived로 분류되어 bugs 증가 없이 정리된다."""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        state = make_state(fake_r)

        rid = "rs-auto-h1"
        plan_file = tmp_path / "docs" / "plan" / "2026-04-03_auto-next.md"
        history_file = tmp_path / "docs" / "history" / "2026-04-03_auto-next.md"
        plan_file.parent.mkdir(parents=True)
        history_file.parent.mkdir(parents=True)
        history_file.write_text("archived", encoding="utf-8")

        await fake_r.zadd(RECENT_RUNNERS_KEY, {rid: 1})
        await fake_r.set(runner_key(rid, "status"), "stopped")
        await fake_r.set(runner_key(rid, "plan_file"), str(plan_file))
        await fake_r.set(runner_key(rid, "stop_stage"), "post_review")

        result = await state.cleanup_stale_runners()
        assert result["cleaned_recent"] == 1
        assert result["bugs"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_stale_pre_review_running_grace_B(self, tmp_path):
        """stop_stage=pre_review + running + grace 내 file_lost는 즉시 정리되지 않는다."""
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        state = make_state(fake_r)

        rid = "rs-pre-grace"
        plan_file = tmp_path / "docs" / "plan" / "2026-04-03_fix.md"
        plan_file.parent.mkdir(parents=True)

        await fake_r.zadd(RECENT_RUNNERS_KEY, {rid: 1})
        await fake_r.set(runner_key(rid, "status"), "running")
        await fake_r.set(runner_key(rid, "plan_file"), str(plan_file))
        await fake_r.set(runner_key(rid, "stop_stage"), "pre_review")
        await fake_r.set(
            runner_key(rid, "start_time"),
            (datetime.now() - timedelta(minutes=3)).isoformat(),
        )

        result = await state.cleanup_stale_runners()
        assert result["cleaned_recent"] == 0


class TestRecentTtlContract:
    def _import_ttl_modules(self):
        import app.modules.dev_runner.services.redis_connection as redis_connection

        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import _dr_constants as dr_constants
        return redis_connection, dr_constants

    def test_recent_ttl_contract_right_default_86400(self, monkeypatch):
        monkeypatch.delenv("DEV_RUNNER_RECENT_TTL_SECONDS", raising=False)
        redis_connection, dr_constants = self._import_ttl_modules()
        redis_connection = importlib.reload(redis_connection)
        dr_constants = importlib.reload(dr_constants)

        assert redis_connection.RECENT_RUNNERS_TTL == 86400
        assert dr_constants.RECENT_RUNNERS_TTL == 86400

    def test_recent_ttl_contract_boundary_env_override(self, monkeypatch):
        monkeypatch.setenv("DEV_RUNNER_RECENT_TTL_SECONDS", "7200")
        redis_connection, dr_constants = self._import_ttl_modules()
        try:
            redis_connection = importlib.reload(redis_connection)
            dr_constants = importlib.reload(dr_constants)

            assert redis_connection.RECENT_RUNNERS_TTL == 7200
            assert dr_constants.RECENT_RUNNERS_TTL == 7200
        finally:
            monkeypatch.delenv("DEV_RUNNER_RECENT_TTL_SECONDS", raising=False)
            importlib.reload(redis_connection)
            importlib.reload(dr_constants)

    def test_recent_ttl_contract_error_invalid_env_fallback(self, monkeypatch):
        monkeypatch.setenv("DEV_RUNNER_RECENT_TTL_SECONDS", "invalid")
        redis_connection, dr_constants = self._import_ttl_modules()
        try:
            redis_connection = importlib.reload(redis_connection)
            dr_constants = importlib.reload(dr_constants)

            assert redis_connection.RECENT_RUNNERS_TTL == 86400
            assert dr_constants.RECENT_RUNNERS_TTL == 86400
        finally:
            monkeypatch.delenv("DEV_RUNNER_RECENT_TTL_SECONDS", raising=False)
            importlib.reload(redis_connection)
            importlib.reload(dr_constants)
