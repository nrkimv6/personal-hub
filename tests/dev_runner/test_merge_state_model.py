from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = ROOT / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))


def test_approval_required_to_queued_requires_approved_retry():
    from _dr_merge_state import APPROVAL_REQUIRED, QUEUED, RetryAction, is_transition_allowed

    assert not is_transition_allowed(APPROVAL_REQUIRED, QUEUED, RetryAction.INLINE_MERGE)
    assert is_transition_allowed(APPROVAL_REQUIRED, QUEUED, RetryAction.APPROVED_RETRY)


def test_terminal_statuses_reject_inline_and_retry_merge():
    from _dr_merge_state import QUEUED, RetryAction, TERMINAL_STATUSES, is_transition_allowed

    for status in TERMINAL_STATUSES:
        assert not is_transition_allowed(status, QUEUED, RetryAction.INLINE_MERGE)
        assert not is_transition_allowed(status, QUEUED, RetryAction.RETRY_MERGE)


def test_should_enter_inline_merge_blocks_terminal_approval():
    from _dr_merge_state import APPROVAL_REQUIRED, should_enter_inline_merge

    assert not should_enter_inline_merge(APPROVAL_REQUIRED, merge_requested=True, exit_code=0, stop_stage=None)


def test_decide_cleanup_action_blocks_terminal_state():
    from _dr_merge_persistence import MergeState
    from _dr_merge_state import APPROVAL_REQUIRED, MergeCleanupAction
    from _dr_stream_cleanup import decide_cleanup_action

    decision = decide_cleanup_action(
        MergeState(merge_status=APPROVAL_REQUIRED, merge_requested=True),
        exit_code=0,
        exit_reason="completed",
        stop_stage=None,
        completed_for_flow=True,
        has_worktree_commits=True,
    )

    assert decision.action == MergeCleanupAction.BLOCKED_TERMINAL
