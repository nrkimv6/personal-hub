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
from plan_worktree_helpers import parse_plan_worktree_info, write_plan_worktree_info  # noqa: E402
from _dr_plan_runner import (  # noqa: E402
    _ensure_test_repo_plan_materialized,
    _resolve_subprocess_plan_file,
    _should_write_canonical_plan_header,
)
from _dr_merge import _resolve_post_merge_plan_file  # noqa: E402


class _FakeRedis:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str):
        return self._values.get(key)


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


def test_test_repo_root_runner_uses_worktree_plan_for_subprocess(tmp_path):
    repo = tmp_path / "isolated-repo"
    _init_repo(repo)
    plan = repo / "docs" / "plan" / "dummy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# dummy\n", encoding="utf-8")
    _run(["git", "add", "docs/plan/dummy.md"], repo)
    _run(["git", "commit", "-m", "test: add dummy plan"], repo)

    worktree_path, _branch = WorktreeManager.create(
        "t-real_dummy_plan-5678",
        repo / ".worktrees",
        plan_file=str(plan),
        use_runner_identity=True,
    )
    _ensure_test_repo_plan_materialized(str(plan), worktree_path)

    effective = _resolve_subprocess_plan_file(
        str(plan),
        worktree_path,
        repo,
        use_worktree_plan=True,
    )

    assert effective == str(worktree_path / "docs" / "plan" / "dummy.md")


def test_test_repo_root_worktree_plan_can_receive_required_headers(tmp_path):
    repo = tmp_path / "isolated-repo"
    _init_repo(repo)
    plan = repo / "docs" / "plan" / "dummy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# dummy\n\n> 상태: 구현중\n", encoding="utf-8")
    _run(["git", "add", "docs/plan/dummy.md"], repo)
    _run(["git", "commit", "-m", "test: add dummy plan"], repo)

    worktree_path, branch = WorktreeManager.create(
        "t-real_dummy_plan-9012",
        repo / ".worktrees",
        plan_file=str(plan),
        use_runner_identity=True,
    )
    _ensure_test_repo_plan_materialized(str(plan), worktree_path)
    worktree_plan = worktree_path / "docs" / "plan" / "dummy.md"
    worktree_rel = str(worktree_path.relative_to(repo)).replace("\\", "/")

    assert write_plan_worktree_info(str(worktree_plan), branch, worktree_rel, owner=str(plan))

    header_branch, header_worktree = parse_plan_worktree_info(str(worktree_plan))
    assert header_branch == branch
    assert header_worktree == worktree_rel


def test_normal_runner_keeps_canonical_plan_for_subprocess(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    plan = repo / "docs" / "plan" / "dummy.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# dummy\n", encoding="utf-8")
    worktree_path = repo / ".worktrees" / "runner"
    worktree_path.mkdir(parents=True)

    effective = _resolve_subprocess_plan_file(
        str(plan),
        worktree_path,
        repo,
        use_worktree_plan=False,
    )

    assert effective == str(plan)


def test_test_repo_root_does_not_write_canonical_plan_header():
    assert _should_write_canonical_plan_header({"test_repo_root": "C:/tmp/repo"}) is False
    assert _should_write_canonical_plan_header({}) is True


def test_post_merge_done_prefers_canonical_plan_metadata(tmp_path):
    repo = tmp_path / "isolated-repo"
    _init_repo(repo)
    canonical_plan = repo / "docs" / "plan" / "dummy.md"
    canonical_plan.parent.mkdir(parents=True)
    canonical_plan.write_text("# dummy\n> 상태: 머지대기\n", encoding="utf-8")

    worktree = repo / ".worktrees" / "runner-a"
    worktree_plan = worktree / "docs" / "plan" / "dummy.md"
    worktree_plan.parent.mkdir(parents=True)
    worktree_plan.write_text("# dummy\n> 상태: 머지대기\n", encoding="utf-8")

    runner_id = "runner-a"
    redis_client = _FakeRedis(
        {
            f"plan-runner:runners:{runner_id}:canonical_plan_file": str(canonical_plan),
            f"plan-runner:runners:{runner_id}:worktree_path": str(worktree),
            f"plan-runner:runners:{runner_id}:test_source": "real_dummy_plan_playwright",
            f"plan-runner:runners:{runner_id}:test_repo_root": str(repo),
            f"plan-runner:runners:{runner_id}:test_repo_root_allowed": "1",
        }
    )

    resolved = _resolve_post_merge_plan_file(str(worktree_plan), runner_id, redis_client)

    assert resolved == str(canonical_plan)
