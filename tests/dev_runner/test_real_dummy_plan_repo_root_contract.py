"""Local integration contract for test-only dev-runner repo root override."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = PROJECT_ROOT / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))

from worktree_manager import WorktreeManager  # noqa: E402


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"cmd={cmd} cwd={cwd}\nstdout={result.stdout}\nstderr={result.stderr}"
    return result


def _init_repo(path: Path) -> None:
    path.mkdir()
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.name", "dev-runner-test"], path)
    _run(["git", "config", "user.email", "dev-runner-test@example.invalid"], path)
    (path / "README.md").write_text("isolated\n", encoding="utf-8")
    _run(["git", "add", "README.md"], path)
    _run(["git", "commit", "-m", "chore: init isolated repo"], path)


def test_worktree_manager_merges_only_isolated_repo(tmp_path):
    repo = tmp_path / "isolated-repo"
    _init_repo(repo)
    marker = "DUMMY_PLAN_PLAYWRIGHT_SENTINEL.txt"
    root_marker = PROJECT_ROOT / marker
    assert not root_marker.exists()

    worktree_path, branch = WorktreeManager.create(
        "t-real_dummy_plan-1234",
        repo / ".worktrees",
        use_runner_identity=True,
    )
    (worktree_path / marker).write_text("merged in isolated repo\n", encoding="utf-8")
    _run(["git", "add", marker], worktree_path)
    _run(["git", "commit", "-m", "test: add dummy plan sentinel"], worktree_path)

    merge_result = WorktreeManager.merge_to_main(
        "t-real_dummy_plan-1234",
        repo / ".worktrees",
        repo,
        branch=branch,
        use_runner_identity=True,
    )

    assert merge_result.success, merge_result.message
    assert (repo / marker).read_text(encoding="utf-8") == "merged in isolated repo\n"
    assert not root_marker.exists()
