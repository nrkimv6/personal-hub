from app.modules.dev_runner.services.runner_display_state import build_display_state
from app.modules.dev_runner.services.runner_read_model import RunnerReadModel
from app.modules.dev_runner.services.runner_git_metadata import RunnerGitMetadata


def _model(**overrides):
    values = {
        "runner_id": "runner-1",
        "running": False,
        "merge_status": None,
        "exit_reason": None,
        "remaining_post_merge_tasks": 0,
        "merge_evidence_missing": False,
        "git": RunnerGitMetadata(
            branch="impl/test",
            worktree_path="D:/worktree",
            branch_exists=True,
            worktree_exists=True,
        ),
    }
    values.update(overrides)
    return RunnerReadModel(**values)


def test_merge_error_wins_over_completed_exit_reason():
    display = build_display_state(_model(merge_status="error", exit_reason="completed"))

    assert display.state == "merge_error"
    assert display.label == "머지 오류"
    assert display.severity == "error"


def test_approval_required_hides_stale_branch_badge():
    display = build_display_state(
        _model(
            merge_status="approval_required",
            git=RunnerGitMetadata(
                branch="impl/test",
                worktree_path="D:/worktree",
                branch_exists=False,
                worktree_exists=True,
            ),
        )
    )

    assert display.state == "approval_required"
    assert display.severity == "approval"
    assert display.hide_stale_branch_badge is True
    assert display.secondary is None


def test_stopped_runner_with_approval_required_displays_approval_R():
    display = build_display_state(
        _model(running=False, merge_status="approval_required", exit_reason="completed")
    )

    assert display.state == "approval_required"
    assert display.label == "승인 필요"
    assert display.severity == "approval"


def test_post_merge_tasks_prevent_plain_completed_label():
    display = build_display_state(
        _model(exit_reason="completed", remaining_post_merge_tasks=2)
    )

    assert display.state == "post_merge_pending"
    assert display.label == "후처리 필요"
    assert display.severity == "warn"
