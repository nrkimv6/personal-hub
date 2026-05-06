"""test_stream_cleanup_helpers.py — _update_workflow_and_execute_cleanup 단위 TC

RIGHT-BICEP + CORRECT 원칙으로 작성.
"""
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# plan_runner scripts 폴더를 sys.path에 추가
_SCRIPTS = Path(__file__).parent.parent.parent / "scripts" / "plan_runner"
sys.path.insert(0, str(_SCRIPTS))

from _dr_stream_cleanup import (
    _StreamCleanupCtx,
    _determine_merge_requested,
    _has_worktree_commits,
    _update_workflow_and_execute_cleanup,
)


def _make_ctx(
    *,
    runner_id="test-runner",
    exit_code=0,
    exit_reason="completed",
    stop_stage=None,
    completed_for_flow=True,
    wf_manager=None,
    failure_message="exit_code=0; exit_reason=completed",
):
    rc = MagicMock()
    ctx = _StreamCleanupCtx(
        runner_id=runner_id,
        redis_client=rc,
        log_channel=f"dev-runner:log:{runner_id}",
        exit_code=exit_code,
        wf_manager=wf_manager,
    )
    ctx.exit_reason = exit_reason
    ctx.stop_stage = stop_stage
    ctx.completed_for_flow = completed_for_flow
    ctx.failure_message = failure_message
    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# _update_workflow_and_execute_cleanup tests
# ──────────────────────────────────────────────────────────────────────────────

class TestUwecMergePath:
    """merge_requested=True 시 _do_inline_merge 호출"""

    def test_uwec_merge_path_calls_do_inline_merge(self):
        wf_manager = MagicMock()
        wf_manager.get_by_runner_id.return_value = {"id": 1}
        ctx = _make_ctx(exit_code=0, wf_manager=wf_manager)

        with patch("_dr_stream_cleanup._do_inline_merge") as mock_merge, \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
            _update_workflow_and_execute_cleanup(ctx, merge_requested=True)

        mock_merge.assert_called_once_with("test-runner", ctx.redis_client)
        # _do_inline_merge 내부에서 cleanup 호출하므로 외부에서는 호출하지 않음
        mock_cleanup.assert_not_called()


class TestUwecFallbackPath:
    """merge_requested=False + detect_merged_but_not_done 반환값 있을 때 _handle_post_merge_done 호출"""

    def test_uwec_fallback_path_calls_handle_post_merge_done(self):
        ctx = _make_ctx(exit_code=0)
        detect_result = {"plan_file": "docs/plan/test.md"}

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=detect_result), \
             patch("_dr_stream_cleanup._handle_post_merge_done", return_value={"success": True}) as mock_done, \
             patch("_dr_stream_cleanup._cleanup_process_state"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

        mock_done.assert_called_once()
        args = mock_done.call_args
        assert args[0][0] == "docs/plan/test.md"
        assert args[0][1] == "test-runner"


class TestUwecNoDetect:
    """merge_requested=False + detect 없음 → _cleanup_process_state 호출"""

    def test_uwec_no_detect_calls_cleanup_process_state(self):
        ctx = _make_ctx(exit_code=0)

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
             patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup:
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

        mock_cleanup.assert_called_once_with("test-runner", ctx.redis_client)


class TestUwecWorkflowStatus:
    """Workflow 상태 업데이트 분기 검증"""

    def test_uwec_exit0_completed_workflow_completed(self):
        wf_manager = MagicMock()
        wf_manager.get_by_runner_id.return_value = {"id": 42}
        ctx = _make_ctx(exit_code=0, completed_for_flow=True, wf_manager=wf_manager)

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
             patch("_dr_stream_cleanup._cleanup_process_state"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

        wf_manager.update_status.assert_called_once_with(42, "completed")

    def test_uwec_exit0_not_completed_workflow_failed(self):
        wf_manager = MagicMock()
        wf_manager.get_by_runner_id.return_value = {"id": 42}
        ctx = _make_ctx(
            exit_code=0, completed_for_flow=False,
            failure_message="exit_code=0; exit_reason=stopped",
            wf_manager=wf_manager,
        )

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
             patch("_dr_stream_cleanup._cleanup_process_state"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

        wf_manager.update_status.assert_called_once_with(
            42, "failed", error_message="exit_code=0; exit_reason=stopped"
        )

    def test_uwec_exit_nonzero_workflow_failed(self):
        wf_manager = MagicMock()
        wf_manager.get_by_runner_id.return_value = {"id": 42}
        ctx = _make_ctx(
            exit_code=1, completed_for_flow=False,
            failure_message="exit_code=1; exit_reason=error",
            wf_manager=wf_manager,
        )

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
             patch("_dr_stream_cleanup._cleanup_process_state"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

        wf_manager.update_status.assert_called_once_with(
            42, "failed", error_message="exit_code=1; exit_reason=error"
        )

    def test_uwec_merge_requested_workflow_merge_pending(self):
        wf_manager = MagicMock()
        wf_manager.get_by_runner_id.return_value = {"id": 42}
        ctx = _make_ctx(exit_code=0, wf_manager=wf_manager)

        with patch("_dr_stream_cleanup._do_inline_merge"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=True)

        wf_manager.update_status.assert_called_once_with(42, "merge_pending")

    def test_uwec_wf_manager_none_no_exception(self):
        """wf_manager=None → 예외 없이 종료"""
        ctx = _make_ctx(exit_code=0, wf_manager=None)

        with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
             patch("_dr_stream_cleanup._cleanup_process_state"):
            _update_workflow_and_execute_cleanup(ctx, merge_requested=False)  # should not raise


# ──────────────────────────────────────────────────────────────────────────────
# _determine_merge_requested: exit_code!=0 분기 _has_worktree_commits 경유 검증
# ──────────────────────────────────────────────────────────────────────────────

class TestDetermineMergeRequestedNonzeroExitUsesHelper:
    """exit_code!=0 분기에서 subprocess.run 직접 호출 없이 _has_worktree_commits 경유 (🟡 YELLOW 해소 검증)"""

    def test_exit_nonzero_uses_has_worktree_commits_true(self):
        ctx = _make_ctx(exit_code=1, completed_for_flow=False)
        ctx.redis_client.get.return_value = b"some-flag"  # merge_requested 플래그 있음

        with patch("_dr_stream_cleanup._has_worktree_commits", return_value=True) as mock_hwc, \
             patch("subprocess.run") as mock_subproc:
            result = _determine_merge_requested(ctx)

        mock_hwc.assert_called_once()
        mock_subproc.assert_not_called()
        assert result is True

    def test_exit_nonzero_uses_has_worktree_commits_false(self):
        ctx = _make_ctx(exit_code=1, completed_for_flow=False)
        ctx.redis_client.get.return_value = b"some-flag"  # merge_requested 플래그 있음

        with patch("_dr_stream_cleanup._has_worktree_commits", return_value=False) as mock_hwc, \
             patch("subprocess.run") as mock_subproc:
            result = _determine_merge_requested(ctx)

        mock_hwc.assert_called_once()
        mock_subproc.assert_not_called()
        assert result is False


def _redis_getter(values: dict[str, object]):
    def _get(key):
        return values.get(key)
    return _get


def test_has_worktree_commits_falls_back_to_plan_header_branch(tmp_path):
    runner_id = "runner-plan-header"
    plan = tmp_path / "plan.md"
    plan.write_text(
        "> 상태: 구현중\n"
        "> branch: impl/post-merge-only\n"
        "> worktree: .worktrees/impl-post-merge-only\n\n"
        "## TODO\n- [ ] task\n",
        encoding="utf-8",
    )
    redis_client = MagicMock()
    redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:branch": None,
        f"plan-runner:runners:{runner_id}:worktree_path": None,
        f"plan-runner:runners:{runner_id}:plan_file": str(plan),
    })
    proc = MagicMock(returncode=0, stdout="abc123 fix\n")

    with patch("subprocess.run", return_value=proc):
        assert _has_worktree_commits(runner_id, redis_client) is True

    redis_client.set.assert_any_call(f"plan-runner:runners:{runner_id}:branch", "impl/post-merge-only")
    redis_client.set.assert_any_call(f"plan-runner:runners:{runner_id}:worktree_path", ".worktrees/impl-post-merge-only")


def test_has_worktree_commits_falls_back_to_worktree_head(tmp_path):
    runner_id = "runner-worktree-head"
    worktree = tmp_path / "wt"
    worktree.mkdir()
    redis_client = MagicMock()
    redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:branch": None,
        f"plan-runner:runners:{runner_id}:worktree_path": str(worktree),
        f"plan-runner:runners:{runner_id}:plan_file": None,
        f"plan-runner:recent-meta:{runner_id}": None,
    })
    rev_parse = MagicMock(returncode=0, stdout="impl/from-head\n")
    log = MagicMock(returncode=0, stdout="abc123 fix\n")

    with patch("subprocess.run", side_effect=[rev_parse, log]):
        assert _has_worktree_commits(runner_id, redis_client) is True

    redis_client.set.assert_any_call(f"plan-runner:runners:{runner_id}:branch", "impl/from-head")
    redis_client.set.assert_any_call(f"plan-runner:runners:{runner_id}:worktree_path", str(worktree))


def test_has_worktree_commits_no_evidence_returns_false_with_log():
    runner_id = "runner-no-evidence"
    redis_client = MagicMock()
    redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:branch": None,
        f"plan-runner:runners:{runner_id}:worktree_path": None,
        f"plan-runner:runners:{runner_id}:plan_file": None,
        f"plan-runner:recent-meta:{runner_id}": None,
    })

    with patch("_dr_stream_cleanup._pub_and_log") as pub:
        assert _has_worktree_commits(runner_id, redis_client) is False

    assert any("MERGE-EVIDENCE-MISSING" in call.args[1] for call in pub.call_args_list)


def test_determine_merge_requested_reads_suffix_key_only():
    runner_id = "runner-suffix-only"
    ctx = _make_ctx(runner_id=runner_id, exit_code=0, completed_for_flow=True)
    ctx.redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:merge_requested": None,
        f"plan-runner:runner:{runner_id}": {"merge_requested": "true"},
    })

    with patch("_dr_stream_cleanup._has_worktree_commits", return_value=False):
        assert _determine_merge_requested(ctx) is False

    requested_keys = [call.args[0] for call in ctx.redis_client.get.call_args_list]
    assert f"plan-runner:runners:{runner_id}:merge_requested" in requested_keys
    assert f"plan-runner:runner:{runner_id}" not in requested_keys


def test_completed_post_merge_only_without_merge_requested_updates_merge_pending(tmp_path):
    runner_id = "runner-post-merge-only"
    plan = tmp_path / "plan.md"
    plan.write_text(
        "> 상태: 구현중\n\n"
        "### Phase T4: E2E\n\n"
        "- [ ] run e2e\n",
        encoding="utf-8",
    )
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 77}
    ctx = _make_ctx(runner_id=runner_id, exit_code=0, completed_for_flow=True, wf_manager=wf_manager)
    ctx.redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:plan_file": str(plan),
    })

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._do_inline_merge") as merge, \
         patch("_dr_stream_cleanup._cleanup_process_state"):
        _update_workflow_and_execute_cleanup(ctx, merge_requested=False)

    wf_manager.update_status.assert_called_once_with(77, "merge_pending")
    merge.assert_called_once_with(runner_id, ctx.redis_client)
