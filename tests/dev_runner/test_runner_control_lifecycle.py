"""test_runner_control_lifecycle.py — _dr_runner_control lifecycle smoke 테스트

검증 범위:
- start_plan_runner: runner_id 없으면 에러 반환
- stop_plan_runner: 실행 중이 아닌 runner에 Not running 반환
- get_status: 실행 중 runner 목록 조회
- force_stop_plan_runner: runner 없을 때 정상 반환
- force_kill_plan_runner: runner_id 없으면 에러 반환
- 모듈 분리 검증: _dr_plan_runner 파사드 re-export 호환성
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# noise 필터 모킹
_noise_mod = types.ModuleType("listener_noise_filter")
_noise_mod.NOISE_BLOCK_MARKERS = []
_noise_mod.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _noise_mod)


# ---------------------------------------------------------------------------
# 파사드 re-export 검증
# ---------------------------------------------------------------------------

class TestFacadeReexport:
    def test_R_facade_exports_all_lifecycle_functions(self):
        """_dr_plan_runner 파사드가 lifecycle 함수를 모두 re-export해야 한다."""
        import _dr_plan_runner as facade
        expected = [
            "start_plan_runner", "stop_plan_runner", "get_status",
            "force_stop_plan_runner", "force_kill_plan_runner",
            "_do_start_plan_runner", "_launch_plan_runner_process",
            "_stream_output", "_do_inline_merge",
        ]
        for name in expected:
            assert hasattr(facade, name), f"파사드에서 {name} 누락"
            assert callable(getattr(facade, name)), f"{name}이 callable이 아님"

    def test_B_facade_line_count_under_50(self):
        """파사드 파일이 50줄 이하여야 한다 (import/re-export만 있어야 함)."""
        facade_path = _SCRIPTS_DIR / "_dr_plan_runner.py"
        lines = facade_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 50, f"파사드 {len(lines)}줄 — re-export만 남겨야 함"


# ---------------------------------------------------------------------------
# start_plan_runner smoke 테스트
# ---------------------------------------------------------------------------

class TestStartPlanRunner:
    def _make_redis(self):
        return fakeredis.FakeRedis(decode_responses=True)

    def test_R_missing_runner_id_returns_error(self):
        """runner_id 없는 command는 즉시 에러를 반환해야 한다."""
        from _dr_runner_control import start_plan_runner
        redis_client = self._make_redis()

        with patch("_dr_runner_control.get_running_processes", return_value={}):
            result = start_plan_runner({}, redis_client)

        assert result is not None
        assert result["success"] is False
        assert "runner_id" in result["message"].lower()

    def test_B_facade_start_plan_runner_same_behavior(self):
        """파사드의 start_plan_runner가 동일하게 동작해야 한다."""
        from _dr_plan_runner import start_plan_runner
        redis_client = self._make_redis()

        with patch("_dr_runner_control.get_running_processes", return_value={}):
            result = start_plan_runner({}, redis_client)

        assert result is not None
        assert result["success"] is False


# ---------------------------------------------------------------------------
# stop_plan_runner smoke 테스트
# ---------------------------------------------------------------------------

class TestStopPlanRunner:
    def test_R_stop_nonexistent_runner_returns_not_running(self):
        """존재하지 않는 runner 종료 시도 → Not running 반환."""
        from _dr_runner_control import stop_plan_runner
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_runner_control.get_running_processes", return_value={}):
            result = stop_plan_runner("nonexistent-runner", redis_client)

        assert result["success"] is False
        assert "Not running" in result["message"]

    def test_B_stop_finished_process_returns_not_running(self):
        """이미 종료된 프로세스 → Not running 반환."""
        from _dr_runner_control import stop_plan_runner
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        dead_proc = MagicMock()
        dead_proc.poll.return_value = 0  # 이미 종료됨

        with patch("_dr_runner_control.get_running_processes", return_value={"runner-1": dead_proc}):
            result = stop_plan_runner("runner-1", redis_client)

        assert result["success"] is False


# ---------------------------------------------------------------------------
# get_status smoke 테스트
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_R_empty_returns_not_running(self):
        """실행 중 runner 없으면 running=False 반환."""
        from _dr_runner_control import get_status
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_runner_control.get_running_processes", return_value={}), \
             patch("_dr_runner_control.get_running_log_files", return_value={}):
            result = get_status(redis_client)

        assert result["success"] is True
        assert result["running"] is False
        assert result["runners"] == []

    def test_B_alive_process_reported_as_running(self):
        """살아있는 프로세스가 있으면 running=True."""
        from _dr_runner_control import get_status
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        alive_proc = MagicMock()
        alive_proc.poll.return_value = None  # 실행 중
        alive_proc.pid = 9999

        with patch("_dr_runner_control.get_running_processes", return_value={"runner-alive": alive_proc}), \
             patch("_dr_runner_control.get_running_log_files", return_value={"runner-alive": "/tmp/log.txt"}):
            result = get_status(redis_client)

        assert result["running"] is True
        assert len(result["runners"]) == 1
        assert result["runners"][0]["pid"] == 9999


# ---------------------------------------------------------------------------
# force_stop / force_kill smoke 테스트
# ---------------------------------------------------------------------------

class TestForceStop:
    def test_R_force_stop_no_process_returns_success(self):
        """프로세스 없는 runner force_stop → success 반환."""
        from _dr_runner_control import force_stop_plan_runner
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_runner_control.get_running_processes", return_value={}), \
             patch("_dr_runner_control._cleanup_process_state"):
            result = force_stop_plan_runner("ghost-runner", redis_client)

        assert result["success"] is True

    def test_R_force_kill_missing_runner_id_returns_error(self):
        """runner_id 없으면 에러 반환."""
        from _dr_runner_control import force_kill_plan_runner
        redis_client = fakeredis.FakeRedis(decode_responses=True)

        with patch("_dr_runner_control.get_running_processes", return_value={}):
            result = force_kill_plan_runner("", redis_client)

        assert result["success"] is False
        assert "runner_id" in result["message"].lower()
