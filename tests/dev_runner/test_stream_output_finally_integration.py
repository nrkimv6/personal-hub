"""T3: _stream_output() finally 블록 통합 검증 (fakeredis pub/sub).

검증 범위:
- merge/cleanup 판정 로그가 Redis 채널로 실제 publish 되는지
- exit_reason=rate_limit일 때 workflow가 completed로 오분류되지 않는지
- __COMPLETED::{reason}__ 이벤트 reason이 Redis 저장값과 일치하는지
"""
from __future__ import annotations

import importlib.util
import io
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_runtime_utils import _normalize_exit_reason


RUNNER_KEY_PREFIX = "plan-runner:runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"


def _load_plan_runner_mod():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    script_path = scripts_dir / "_dr_plan_runner.py"
    if not script_path.exists():
        pytest.skip(f"_dr_plan_runner.py not found: {script_path}")
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # noise 필터 의존성을 테스트에서 고정
    noise_mod = types.ModuleType("listener_noise_filter")
    noise_mod.NOISE_BLOCK_MARKERS = []
    noise_mod.is_noise_line = lambda line: False
    sys.modules["listener_noise_filter"] = noise_mod

    spec = importlib.util.spec_from_file_location("_dr_plan_runner_integ", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plan_runner_mod():
    return _load_plan_runner_mod()


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fr(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def fr_sub(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


def _make_process(returncode=0):
    proc = MagicMock()
    proc.stdout = io.StringIO("")
    proc.returncode = returncode
    proc.wait.return_value = returncode
    proc.poll.return_value = returncode
    return proc


def _make_wf_manager(runner_id: str = "test-runner"):
    wf = {"id": 99, "runner_id": runner_id, "status": "running"}
    mgr = MagicMock()
    mgr.get_by_runner_id.return_value = wf
    return mgr, wf


def _publish_cleanup_sentinel(rid: str, redis_client):
    reason = _normalize_exit_reason(redis_client.get(f"{RUNNER_KEY_PREFIX}:{rid}:exit_reason"))
    redis_client.publish(f"{LOG_CHANNEL_PREFIX}:{rid}", f"__COMPLETED::{reason}__")


class TestStreamOutputFinallyIntegration:
    def test_stream_output_finally_merge_logs_in_pubsub(self, plan_runner_mod, fr, fr_sub):
        """finally 블록에서 merge_requested 플래그 있을 때 merge 분기 로그가 pub/sub 구독자로 전달된다."""
        runner_id = "t3-finally-pubsub-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        # merge_requested 플래그 세팅 → CLEANUP 채널에 "merge 분기 판정" 출력
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)  # subscribe ack consume

        received = []

        def _subscriber():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg.get("type") == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=_subscriber, daemon=True)
        t.start()

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)

        # merge_requested 플래그 있을 때만 CLEANUP 채널에 "merge 분기 판정" 출력
        assert any("merge 분기 판정" in msg for msg in received), (
            f"merge 분기 판정 로그 미수신. received={received}"
        )
        assert any("[CLEANUP]" in msg for msg in received), (
            f"[CLEANUP] 태그 로그 미수신. received={received}"
        )

        pubsub.close()

    def test_stream_output_finally_rate_limit_reason_keeps_non_completed(self, plan_runner_mod, fr):
        """exit_reason=rate_limit이면 workflow completed 금지 + completed 이벤트 reason 일치."""
        runner_id = "t3-finally-rate-limit-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "rate_limit")

        published = []
        orig_publish = fr.publish

        def _capture_publish(channel, message):
            published.append((channel, message))
            return orig_publish(channel, message)

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, wf = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state", side_effect=_publish_cleanup_sentinel), \
             patch.object(fr, "publish", side_effect=_capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        wf_mgr.update_status.assert_any_call(
            wf["id"], "failed", error_message="exit_code=0; exit_reason=rate_limit"
        )
        assert not any(
            len(c.args) >= 2 and c.args[1] == "completed"
            for c in wf_mgr.update_status.call_args_list
        ), "rate_limit 경로에서 workflow completed 오분류가 발생함"

        assert any(
            channel == log_channel and msg == "__COMPLETED::rate_limit__"
            for channel, msg in published
        ), f"__COMPLETED::rate_limit__ publish 누락. published={published}"

    def test_stream_output_finally_missing_exit_reason_publishes_error(self, plan_runner_mod, fr):
        """exit_reason 누락 시 completed fallback 대신 error sentinel을 publish한다."""
        runner_id = "t3-finally-missing-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        published = []
        orig_publish = fr.publish

        def _capture_publish(channel, message):
            published.append((channel, message))
            return orig_publish(channel, message)

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, wf = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state", side_effect=_publish_cleanup_sentinel), \
             patch.object(fr, "publish", side_effect=_capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        wf_mgr.update_status.assert_any_call(
            wf["id"], "failed", error_message="exit_code=0; exit_reason=error"
        )
        assert any(
            channel == log_channel and msg == "__COMPLETED::error__"
            for channel, msg in published
        ), f"__COMPLETED::error__ publish 누락. published={published}"

    def test_stream_output_finally_commit_failed_preserves_scope_detail(self, plan_runner_mod, fr):
        """commit_failed 종료 시 detail 라인과 summary 메시지가 둘 다 보존된다."""
        import tempfile

        runner_id = "t3-finally-commit-failed-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "commit_failed")

        published = []
        orig_publish = fr.publish

        def _capture_publish(channel, message):
            published.append((channel, message))
            return orig_publish(channel, message)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
            f.write("[INFO] unrelated line\n")
            f.write("failed_projects=monitor-page\n")
            f.write("dirty_files=app/modules/dev_runner/services/event_service.py\n")
            f.write("commit_scope=docs/plan/test.md\n")
            log_path = f.name

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, wf = _make_wf_manager(runner_id)

        try:
            with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
                 patch.object(plan_runner_mod, "get_running_log_files", return_value={runner_id: log_path}), \
                 patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
                 patch.object(plan_runner_mod, "_do_inline_merge"), \
                 patch.object(plan_runner_mod, "_cleanup_process_state", return_value=None), \
                 patch.object(fr, "publish", side_effect=_capture_publish):
                plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

            error_message = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:error")
            assert error_message is not None
            assert error_message.startswith("exit_code=0; exit_reason=commit_failed")
            assert "detail=commit_scope=docs/plan/test.md" in error_message
            wf_mgr.update_status.assert_any_call(
                wf["id"],
                "failed",
                error_message=error_message,
            )
            assert any(
                channel == log_channel and msg == "[ERROR] commit_scope=docs/plan/test.md"
                for channel, msg in published
            ), f"commit_failed detail publish 누락. published={published}"
        finally:
            try:
                import os

                os.unlink(log_path)
            except Exception:
                pass

    def test_immediate_exit_error_visibility_integration(self, plan_runner_mod, fr, fr_sub):
        """T3: 즉시 종료(stdout 없음, exit_code=15) 시 [ERROR] 메시지가 채널에 발행되고, merge 노이즈 없음."""
        runner_id = "t3-err-vis-integ-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)  # subscribe ack consume

        received = []

        def _subscriber():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg.get("type") == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=_subscriber, daemon=True)
        t.start()

        process = _make_process(returncode=15)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"), \
             patch.object(plan_runner_mod, "_pick_error_detail_line", return_value=None), \
             patch.object(plan_runner_mod, "_load_log_tail_lines", return_value=[]):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)
        pubsub.close()

        # [ERROR] 메시지가 1건 이상 채널에 발행됨
        error_msgs = [m for m in received if "[ERROR]" in m]
        assert error_msgs, f"[ERROR] 메시지가 채널에 미발행. received={received}"
        assert any("exit_code=15" in m for m in error_msgs), \
            f"exit_code=15 포함 [ERROR] 없음. error_msgs={error_msgs}"

        # "merge 분기 판정" 메시지가 채널에 publish되지 않음 (debug 레벨로만 기록)
        assert not any("merge 분기 판정" in m for m in received), \
            f"merge 분기 판정 노이즈가 채널에 publish됨. received={received}"

    def test_error_exit_with_detail_integration(self, plan_runner_mod, fr, fr_sub):
        """T3 회귀: _error_detail 존재 시 기존 [ERROR] {detail} 포맷 유지."""
        runner_id = "t3-err-detail-integ-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        received = []

        def _subscriber():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg.get("type") == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=_subscriber, daemon=True)
        t.start()

        process = _make_process(returncode=1)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"), \
             patch.object(plan_runner_mod, "_pick_error_detail_line", return_value="SomeError: integration test"), \
             patch.object(plan_runner_mod, "_load_log_tail_lines", return_value=["SomeError: integration test"]):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)
        pubsub.close()

        error_msgs = [m for m in received if "[ERROR]" in m]
        assert any("SomeError: integration test" in m for m in error_msgs), \
            f"[ERROR] SomeError 미수신. error_msgs={error_msgs}"
        # _failure_message 포맷이 아닌 원문이 publish되어야 함
        assert not any("exit_code=" in m and "SomeError" not in m for m in error_msgs), \
            f"_failure_message 포맷이 잘못 publish됨: {error_msgs}"


class TestStreamOutputE2EFlow:
    """T4: finally 블록 전체 흐름 E2E 검증"""

    def test_error_exit_no_stdout_full_finally_flow(self, plan_runner_mod, fr, fr_sub):
        """T4: 에러 종료 시 finally 블록 전체 흐름 — [ERROR] publish + workflow failed + cleanup."""
        runner_id = "t4-full-flow-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "error")

        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        received = []

        def _subscriber():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg.get("type") == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=_subscriber, daemon=True)
        t.start()

        process = _make_process(returncode=15)
        log_handle = io.StringIO()
        wf_mgr, wf = _make_wf_manager(runner_id)

        cleanup_called = []

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
             patch.object(plan_runner_mod, "_cleanup_process_state", side_effect=lambda rid, rc, **kw: cleanup_called.append(rid)), \
             patch.object(plan_runner_mod, "_pick_error_detail_line", return_value=None), \
             patch.object(plan_runner_mod, "_load_log_tail_lines", return_value=[]):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)
        pubsub.close()

        # (1) 채널에 [ERROR] 메시지 발행됨
        error_msgs = [m for m in received if "[ERROR]" in m]
        assert error_msgs, f"[ERROR] 메시지 미발행. received={received}"
        assert any("exit_code=15" in m for m in error_msgs), \
            f"exit_code=15 포함 [ERROR] 없음. error_msgs={error_msgs}"

        # (2) workflow failed 처리
        from unittest.mock import ANY
        wf_mgr.update_status.assert_any_call(wf["id"], "failed", error_message=ANY)

        # (3) _cleanup_process_state 호출됨
        assert cleanup_called, "_cleanup_process_state 미호출"

        # (4) _do_inline_merge 미호출
        mock_merge.assert_not_called()

    def test_merge_flag_with_completed_full_flow(self, plan_runner_mod, fr, fr_sub):
        """T4 회귀: merge_requested=True + completed 시 merge 흐름 + CLEANUP 로그 발행 유지."""
        runner_id = "t4-merge-flow-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")

        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        pubsub.get_message(timeout=0.1)

        received = []

        def _subscriber():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg.get("type") == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=_subscriber, daemon=True)
        t.start()

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
             patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup:
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)
        pubsub.close()

        # (1) 채널에 "merge 분기 판정" 메시지 포함
        assert any("merge 분기 판정" in m for m in received), \
            f"merge 분기 판정 미발행. received={received}"

        # (2) _do_inline_merge 호출됨
        mock_merge.assert_called_once_with(runner_id, fr)

        # (3) _cleanup_process_state 미호출 (merge 흐름에서는 merge 내부에서 처리)
        mock_cleanup.assert_not_called()
