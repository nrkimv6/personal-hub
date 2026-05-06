"""Integration regression for completed cleanup with post-merge-only residuals."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).parent.parent.parent / "scripts" / "plan_runner"
sys.path.insert(0, str(_SCRIPTS))

from _dr_stream_cleanup import (  # noqa: E402
    _StreamCleanupCtx,
    _determine_merge_requested,
    _update_workflow_and_execute_cleanup,
)


def _redis_getter(values: dict[str, object]):
    def _get(key):
        return values.get(key)
    return _get


def test_branch_missing_post_merge_only_residual_reaches_merge_pending(tmp_path):
    runner_id = "runner-post-merge-only"
    plan = tmp_path / "plan.md"
    plan.write_text(
        "> 상태: 구현중\n"
        "> branch: impl/post-merge-only\n"
        "> worktree: .worktrees/impl-post-merge-only\n\n"
        "### Phase T4: E2E\n\n"
        "- [ ] run e2e\n",
        encoding="utf-8",
    )
    redis_client = MagicMock()
    redis_client.get.side_effect = _redis_getter({
        f"plan-runner:runners:{runner_id}:merge_requested": None,
        f"plan-runner:runners:{runner_id}:branch": None,
        f"plan-runner:runners:{runner_id}:worktree_path": None,
        f"plan-runner:runners:{runner_id}:plan_file": str(plan),
    })
    wf_manager = MagicMock()
    wf_manager.get_by_runner_id.return_value = {"id": 9}
    ctx = _StreamCleanupCtx(
        runner_id=runner_id,
        redis_client=redis_client,
        log_channel=f"plan-runner:logs:{runner_id}",
        exit_code=0,
        wf_manager=wf_manager,
    )
    ctx.exit_reason = "completed"
    ctx.completed_for_flow = True
    ctx.failure_message = "exit_code=0; exit_reason=completed"

    proc = MagicMock(returncode=0, stdout="abc123 fix\n")
    with patch("subprocess.run", return_value=proc), \
         patch("_dr_stream_cleanup._do_inline_merge") as merge, \
         patch("_dr_stream_cleanup._cleanup_process_state"):
        merge_requested = _determine_merge_requested(ctx)
        _update_workflow_and_execute_cleanup(ctx, merge_requested)

    assert merge_requested is True
    redis_client.set.assert_any_call(f"plan-runner:runners:{runner_id}:branch", "impl/post-merge-only")
    redis_client.set.assert_any_call(
        f"plan-runner:runners:{runner_id}:worktree_path",
        ".worktrees/impl-post-merge-only",
    )
    wf_manager.update_status.assert_called_once_with(9, "merge_pending")
    merge.assert_called_once_with(runner_id, redis_client)
