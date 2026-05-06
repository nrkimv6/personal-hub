from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_executor_completed_exit_reason_forces_not_running():
    source = (ROOT / "app/modules/dev_runner/services/executor_service.py").read_text(encoding="utf-8")

    assert 'exit_reason = d["exit_reason"] or recent_meta.get("exit_reason")' in source
    assert 'if exit_reason == "completed":\n                        running = False' in source


def test_recent_meta_preserves_completion_identity_fields():
    source = (ROOT / "scripts/plan_runner/_dr_process_utils.py").read_text(encoding="utf-8")

    for field in (
        '"plan_file"',
        '"display_plan_name"',
        '"engine"',
        '"execution_count"',
        '"log_file_path"',
        '"stream_log_path"',
        '"exit_reason"',
    ):
        assert field in source


def test_runner_list_display_name_fallback_order_is_recent_meta_log_then_worktree_branch():
    source = (ROOT / "app/modules/dev_runner/services/executor_service.py").read_text(encoding="utf-8")

    recent_idx = source.index('display_plan_name = recent_meta.get("display_plan_name")')
    log_idx = source.index("LogFileResolver.parse_meta_from_log")
    worktree_idx = source.index("display_plan_name = Path(worktree_path).name")
    branch_idx = source.index('display_plan_name = branch.split("/")[-1]')

    assert recent_idx < log_idx < worktree_idx < branch_idx
