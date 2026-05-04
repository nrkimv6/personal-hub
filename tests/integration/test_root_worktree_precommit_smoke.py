from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def _copy_hook_scripts(src_root: Path, dst_root: Path) -> None:
    dst_hooks = dst_root / "scripts" / "git-hooks"
    dst_hooks.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        src_root / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1",
        dst_hooks / "pre-commit-plans-block.ps1",
    )
    shutil.copy2(
        src_root / "scripts" / "git-hooks" / "root-branch-guard.ps1",
        dst_hooks / "root-branch-guard.ps1",
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "root-worktree-smoke"], repo)
    _run(["git", "config", "user.email", "root-worktree-smoke@example.com"], repo)

    (repo / ".claude" / "skills" / "done").mkdir(parents=True)
    (repo / "docs" / "DONE.md").parent.mkdir(parents=True)
    (repo / "docs" / "DONE.md").write_text("# DONE\n", encoding="utf-8")
    (repo / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    (repo / ".claude" / "skills" / "done" / "SKILL.md").write_text("base\n", encoding="utf-8")

    _copy_hook_scripts(Path(__file__).resolve().parents[2], repo)

    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _run_hook(repo_cwd: Path) -> subprocess.CompletedProcess[str]:
    hook = repo_cwd / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook)],
        cwd=str(repo_cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_root_worktree_blocks_impl_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("root impl change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_worktree_impl_scope_blocked" in (result.stdout + result.stderr)


def test_root_worktree_allows_commit_ready_merge_with_impl_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "impl/root-merge"], repo)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("branch impl change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)
    _run(["git", "commit", "-m", "impl change"], repo)
    _run(["git", "switch", "main"], repo)
    merge = subprocess.run(
        ["git", "merge", "impl/root-merge", "--no-ff", "--no-commit"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert merge.returncode == 0
    result = _run_hook(repo)

    assert result.returncode == 0


def test_root_worktree_blocks_unresolved_merge_with_impl_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("main impl change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)
    _run(["git", "commit", "-m", "main impl change"], repo)

    _run(["git", "switch", "-c", "impl/root-merge-conflict", "HEAD~1"], repo)
    target.write_text("branch impl change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)
    _run(["git", "commit", "-m", "branch impl change"], repo)
    _run(["git", "switch", "main"], repo)
    merge = subprocess.run(
        ["git", "merge", "impl/root-merge-conflict", "--no-ff", "--no-commit"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert merge.returncode != 0
    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_worktree_impl_scope_blocked" in (result.stdout + result.stderr)


def test_root_worktree_allows_task_ledger_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "TODO.md"
    target.write_text("# TODO\n\n- [ ] ledger\n", encoding="utf-8")
    _run(["git", "add", "TODO.md"], repo)

    result = _run_hook(repo)

    assert result.returncode == 0


def test_root_worktree_blocks_plan_docs_stage(tmp_path):
    repo = _init_repo(tmp_path)
    doc = repo / "docs" / "plan" / "sample.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# plan\n", encoding="utf-8")
    _run(["git", "add", "docs/plan/sample.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "disallowed_worktree" in (result.stdout + result.stderr)


def test_linked_worktree_allows_impl_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "impl-root-fence"
    _run(["git", "worktree", "add", str(worktree), "-b", "impl/root-fence"], repo)

    target = worktree / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("linked dirty\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], worktree)

    result = _run_hook(worktree)

    assert result.returncode == 0


def test_root_non_main_blocks_any_commit(tmp_path):
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "impl/accidental-root"], repo)
    (repo / "TODO.md").write_text("# TODO\n\n- [ ] ledger\n", encoding="utf-8")
    _run(["git", "add", "TODO.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_branch_guard_blocked" in (result.stdout + result.stderr)


def test_plans_worktree_docs_stage_passes_without_conflict(tmp_path):
    repo = _init_repo(tmp_path)
    plans = repo / ".worktrees" / "plans"
    _run(["git", "worktree", "add", str(plans), "-b", "plans"], repo)

    doc = plans / "docs" / "plan" / "sample.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# plan\n", encoding="utf-8")
    _run(["git", "add", "docs/plan/sample.md"], plans)

    result = _run_hook(plans)

    assert result.returncode == 0
