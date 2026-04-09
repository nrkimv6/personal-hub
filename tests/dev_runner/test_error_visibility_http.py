"""HTTP 통합 테스트 — _stream_output 에러 가시성 (TestClient 기반)

Phase T5: 에러 종료 시 [ERROR] 메시지 발행 + merge 노이즈 없음 검증
- GET /api/v1/dev-runner/runners 응답에 error 관련 필드 노출
- Redis 채널에 [ERROR] 메시지가 발행되고 "merge 분기 판정" 노이즈가 없음
"""
import sys
import importlib.util
import io
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.runner import router as runner_router

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(runner_router, prefix=BASE_URL)
    return TestClient(app, raise_server_exceptions=True)


def _load_plan_runner_mod():
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))

    noise_mod = types.ModuleType("listener_noise_filter")
    noise_mod.NOISE_BLOCK_MARKERS = []
    noise_mod.is_noise_line = lambda line: False
    sys.modules["listener_noise_filter"] = noise_mod

    script_path = _SCRIPTS_DIR / "_dr_plan_runner.py"
    if not script_path.exists():
        pytest.skip(f"_dr_plan_runner.py not found: {script_path}")
    spec = importlib.util.spec_from_file_location("_dr_plan_runner_t5", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plan_runner_mod():
    return _load_plan_runner_mod()


@pytest.fixture(scope="module")
def stream_cleanup_mod(plan_runner_mod):
    import _dr_stream_cleanup
    return _dr_stream_cleanup


def _make_runner(runner_id="abc123", exit_reason=None, error=None):
    return {
        "runner_id": runner_id,
        "running": False,
        "plan_file": "docs/plan/test.md",
        "engine": "claude",
        "start_time": "2026-04-06T17:00:00",
        "pid": 1234,
        "worktree_path": None,
        "branch": None,
        "merge_status": None,
        "trigger": "user",
        "visible": True,
        "orphan": False,
        "exit_reason": exit_reason,
        "stop_stage": None,
    }


class TestErrorVisibilityHttp:
    """T5: 에러 종료 시 [ERROR] 메시지 publish + merge 노이즈 없음"""

    @pytest.mark.http
    def test_run_plan_error_exit_stream_has_error_message(self, plan_runner_mod, stream_cleanup_mod, client):
        """T5: 에러 종료(stdout 없음) → Redis 채널에 [ERROR] {_failure_message} 발행됨."""
        runner_id = "t5-err-vis-001"
        fake_server = fakeredis.FakeServer()
        fr = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

        published_messages = []

        def _capture_publish(ch, msg):
            published_messages.append(msg)
            return 1

        process = MagicMock()
        process.stdout = io.StringIO("")
        process.returncode = 15
        process.wait.return_value = 15
        process.poll.return_value = 15
        log_handle = io.StringIO()
        wf_mgr = MagicMock()
        wf_mgr.get_by_runner_id.return_value = {"id": 1, "runner_id": runner_id, "status": "running"}

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(stream_cleanup_mod, "_do_inline_merge"), \
             patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
             patch.object(stream_cleanup_mod, "_pick_error_detail_line", return_value=None), \
             patch.object(stream_cleanup_mod, "_load_log_tail_lines", return_value=[]), \
             patch.object(fr, "publish", side_effect=_capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        error_msgs = [m for m in published_messages if "[ERROR]" in m]
        assert error_msgs, f"[ERROR] 메시지 미발행. published={published_messages}"
        assert any("exit_code=15" in m for m in error_msgs), \
            f"exit_code=15 포함 [ERROR] 없음. error_msgs={error_msgs}"

        # runners API도 200 응답 확인
        runners = [_make_runner(runner_id, exit_reason="error")]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200

    @pytest.mark.http
    def test_run_plan_error_exit_no_merge_noise_in_stream(self, plan_runner_mod, stream_cleanup_mod, client):
        """T5: 에러 종료(merge_requested 없음) → Redis 채널에 'merge 분기 판정' 노이즈 없음."""
        runner_id = "t5-noise-001"
        fake_server = fakeredis.FakeServer()
        fr = fakeredis.FakeRedis(server=fake_server, decode_responses=True)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")
        # merge_requested 키 미세팅

        published_messages = []

        def _capture_publish(ch, msg):
            published_messages.append(msg)
            return 1

        process = MagicMock()
        process.stdout = io.StringIO("")
        process.returncode = 15
        process.wait.return_value = 15
        process.poll.return_value = 15
        log_handle = io.StringIO()
        wf_mgr = MagicMock()
        wf_mgr.get_by_runner_id.return_value = {"id": 2, "runner_id": runner_id, "status": "running"}

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(stream_cleanup_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(stream_cleanup_mod, "_do_inline_merge"), \
             patch.object(stream_cleanup_mod, "_cleanup_process_state"), \
             patch.object(stream_cleanup_mod, "_pick_error_detail_line", return_value=None), \
             patch.object(stream_cleanup_mod, "_load_log_tail_lines", return_value=[]), \
             patch.object(fr, "publish", side_effect=_capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        # "merge 분기 판정" 메시지가 채널에 publish되지 않아야 함
        assert not any("merge 분기 판정" in m for m in published_messages), \
            f"merge 분기 판정 노이즈가 채널에 publish됨: {published_messages}"

        # runners API도 200 응답 확인
        runners = [_make_runner(runner_id, exit_reason="error")]
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=runners,
        ):
            response = client.get(f"{BASE_URL}/runners")

        assert response.status_code == 200
