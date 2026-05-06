from pathlib import Path
import subprocess
from types import SimpleNamespace


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
    log_idx = source.index("LogFileResolver.parse_meta_from_log", recent_idx)
    worktree_idx = source.index("display_plan_name = Path(worktree_path).name", log_idx)
    branch_idx = source.index('display_plan_name = branch.split("/")[-1]', worktree_idx)

    assert recent_idx < log_idx < worktree_idx < branch_idx


def test_check_branch_exists_uses_show_ref_return_code(monkeypatch):
    from app.modules.dev_runner.services.git_utils import check_branch_exists

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("app.modules.dev_runner.services.git_utils.subprocess.run", fake_run)

    assert check_branch_exists("feature/checked-out") is True
    assert calls == [[
        "git",
        "-c",
        "safe.directory=*",
        "show-ref",
        "--verify",
        "--quiet",
        "refs/heads/feature/checked-out",
    ]]


def test_check_branch_exists_detects_checked_out_local_branch_in_git_repo(tmp_path):
    from app.modules.dev_runner.services.git_utils import check_branch_exists

    def run_git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )

    run_git("init")
    run_git("config", "user.email", "test@example.com")
    run_git("config", "user.name", "Test User")
    (tmp_path / "file.txt").write_text("initial\n", encoding="utf-8")
    run_git("add", "file.txt")
    run_git("commit", "-m", "initial")
    run_git("checkout", "-b", "feature/checked-out")

    assert check_branch_exists("feature/checked-out", cwd=str(tmp_path)) is True


def test_approval_required_branch_exists_false_is_corrected_from_worktree(monkeypatch, tmp_path):
    from app.modules.dev_runner.services import executor_service as module

    monkeypatch.setattr(module, "check_branch_exists", lambda branch, cwd=None: branch == "impl/test" and cwd == str(tmp_path))

    branch_exists, checked_at = module._approval_required_branch_exists_fallback(
        "approval_required",
        False,
        "impl/test",
        str(tmp_path),
        "old",
    )

    assert branch_exists is True
    assert checked_at != "old"


def test_approval_required_stale_branch_label_is_suppressed_in_ui():
    instance_source = (ROOT / "frontend/src/lib/components/dev-runner/RunnerInstanceTab.svelte").read_text(encoding="utf-8")
    status_source = (ROOT / "frontend/src/lib/components/dev-runner/RunStatusBar.svelte").read_text(encoding="utf-8")

    assert "if (mergeStatus === 'approval_required') return null;" in instance_source
    assert "mergeStatus !== 'approval_required' && branchExists === false" in instance_source
    assert "if (runner.merge_status === 'approval_required') return null;" in status_source
