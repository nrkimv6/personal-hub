"""listener heartbeat fallback done 실패 전파 단위 테스트."""

from unittest.mock import MagicMock, patch

from tests.dev_runner.conftest import attach_default_redis_behaviors
from tests.dev_runner._path_helpers import load_listener_module


def test_propagate_fallback_done_failure_sets_error_and_workflow_R():
    """R: done 실패 결과가 merge_status/error_message로 전파된다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 101, "status": "running"}

    done_result = {"success": False, "reason": "done_api_failed", "status": "done_failed"}
    with patch.object(mod, "_pub_and_log") as mock_pub:
        mod._propagate_fallback_done_failure(
            runner_id="runner-fb-1",
            done_result=done_result,
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-dead",
        )

    redis_client.set.assert_any_call("plan-runner:runners:runner-fb-1:merge_status", "error")
    wf_manager.update_status.assert_called_once()
    _, kwargs = wf_manager.update_status.call_args
    assert kwargs["error_message"] == "heartbeat-dead fallback done failed: done_api_failed"
    mock_pub.assert_called_once()


def test_propagate_fallback_done_failure_noop_on_success_B():
    """B: done 성공 결과면 부수효과가 없어야 한다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()

    with patch.object(mod, "_pub_and_log") as mock_pub:
        mod._propagate_fallback_done_failure(
            runner_id="runner-fb-2",
            done_result={"success": True, "status": "done_called"},
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-hang",
        )

    redis_client.set.assert_not_called()
    wf_manager.update_status.assert_not_called()
    mock_pub.assert_not_called()


def test_propagate_fallback_done_failure_noop_on_nondict_B():
    """B: dict가 아닌 결과값이면 안전하게 무시한다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()

    with patch.object(mod, "_pub_and_log") as mock_pub:
        mod._propagate_fallback_done_failure(
            runner_id="runner-fb-3",
            done_result=None,
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-hang",
        )

    redis_client.set.assert_not_called()
    wf_manager.update_status.assert_not_called()
    mock_pub.assert_not_called()


def test_execute_heartbeat_done_fallback_hang_failure_updates_workflow_R():
    """R: hang fallback에서 done 실패 시 merge_status/workflow/log가 함께 갱신된다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 201, "status": "running"}

    detect_result = {"plan_file": "D:/tmp/test-plan.md"}
    with patch.object(mod, "_handle_post_merge_done", return_value={"success": False, "reason": "resolver_failed"}) as mock_done, \
         patch.object(mod, "_pub_and_log") as mock_pub:
        mod._execute_heartbeat_done_fallback(
            runner_id="runner-hang-1",
            detect_result=detect_result,
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-hang",
        )

    mock_done.assert_called_once()
    redis_client.set.assert_any_call("plan-runner:runners:runner-hang-1:merge_status", "error")
    wf_manager.update_status.assert_called_once()
    _, kwargs = wf_manager.update_status.call_args
    assert kwargs["error_message"] == "heartbeat-hang fallback done failed: resolver_failed"
    mock_pub.assert_called_once()
    assert mock_pub.call_args.args[0] == "runner-hang-1"
    assert "heartbeat-hang fallback done 실패 전파" in mock_pub.call_args.args[1]
    assert mock_pub.call_args.args[3] == "MERGE-FALLBACK"


def test_execute_heartbeat_done_fallback_dead_failure_updates_workflow_R():
    """R: dead fallback에서 done 실패 시 merge_status/workflow/log가 함께 갱신된다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 202, "status": "running"}

    detect_result = {"plan_file": "D:/tmp/test-plan-dead.md"}
    with patch.object(mod, "_handle_post_merge_done", return_value={"success": False, "reason": "done_api_failed"}) as mock_done, \
         patch.object(mod, "_pub_and_log") as mock_pub:
        mod._execute_heartbeat_done_fallback(
            runner_id="runner-dead-1",
            detect_result=detect_result,
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-dead",
        )

    mock_done.assert_called_once()
    redis_client.set.assert_any_call("plan-runner:runners:runner-dead-1:merge_status", "error")
    wf_manager.update_status.assert_called_once()
    _, kwargs = wf_manager.update_status.call_args
    assert kwargs["error_message"] == "heartbeat-dead fallback done failed: done_api_failed"
    mock_pub.assert_called_once()
    assert mock_pub.call_args.args[0] == "runner-dead-1"
    assert "heartbeat-dead fallback done 실패 전파" in mock_pub.call_args.args[1]
    assert mock_pub.call_args.args[3] == "MERGE-FALLBACK"


def test_propagate_fallback_done_failure_keeps_residue_blocked_reason_R():
    """R: residue_guard fallback 실패는 residue_blocked 상태로 유지한다."""
    mod = load_listener_module("dev_runner_listener_fallback")
    redis_client = attach_default_redis_behaviors(MagicMock())
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 301, "status": "running"}

    with patch.object(mod, "_pub_and_log"):
        mod._propagate_fallback_done_failure(
            runner_id="runner-fb-residue",
            done_result={"success": False, "reason": "residue_guard", "status": "skipped_residue"},
            redis_client=redis_client,
            wf_manager=wf_manager,
            context="heartbeat-hang",
        )

    redis_client.set.assert_any_call("plan-runner:runners:runner-fb-residue:merge_status", "residue_blocked")
