from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


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
    shutil.copy2(
        src_root / "scripts" / "git-hooks" / "post-checkout-root-branch-guard.ps1",
        dst_hooks / "post-checkout-root-branch-guard.ps1",
    )
    shutil.copy2(
        src_root / "scripts" / "git-hooks" / "pre-rebase-root-guard.ps1",
        dst_hooks / "pre-rebase-root-guard.ps1",
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "root-worktree-smoke"], repo)
    _run(["git", "config", "user.email", "root-worktree-smoke@example.com"], repo)

    (repo / ".agents" / "skills" / "done").mkdir(parents=True)
    (repo / ".claude" / "skills" / "done").mkdir(parents=True)
    (repo / ".gemini" / "agents").mkdir(parents=True)
    (repo / "docs" / "DONE.md").parent.mkdir(parents=True)
    (repo / "docs" / "DONE.md").write_text("# DONE\n", encoding="utf-8")
    (repo / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    (repo / ".agents" / "skills" / "done" / "SKILL.md").write_text("base\n", encoding="utf-8")
    (repo / ".claude" / "skills" / "done" / "SKILL.md").write_text("base\n", encoding="utf-8")
    for name in ("ideation.md", "next.md", "plan-list.md", "plan.md"):
        (repo / ".gemini" / "agents" / name).write_text(f"{name}\n", encoding="utf-8")

    _copy_hook_scripts(Path(__file__).resolve().parents[2], repo)

    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _run_hook(repo_cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    hook = repo_cwd / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook)],
        cwd=str(repo_cwd),
        env=process_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _run_root_guard(repo_cwd: Path, mode: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    guard = repo_cwd / "scripts" / "git-hooks" / "root-branch-guard.ps1"
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(guard), "-Mode", mode],
        cwd=str(repo_cwd),
        env=process_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _root_guard_dry_run_env(repo: Path, branch: str, transient: str | None = None) -> dict[str, str]:
    env = {
        "ROOT_GUARD_DRY_RUN": "1",
        "ROOT_GUARD_REPO_ROOT": str(repo),
        "ROOT_GUARD_PROJECT_ROOT": str(repo),
        "ROOT_GUARD_COMMON_GIT_DIR": ".git",
        "ROOT_GUARD_BRANCH": branch,
        "ROOT_GUARD_SENTINEL": str(repo / ".git" / "root-branch-guard.violation"),
    }
    if transient is not None:
        env["ROOT_GUARD_TRANSIENT_DETACHED"] = transient
    return env


def _install_post_checkout_hook(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "post-checkout"
    guard = repo / "scripts" / "git-hooks" / "post-checkout-root-branch-guard.ps1"
    hook.write_text(
        f'#!/bin/sh\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "{guard.as_posix()}" "$1" "$2" "$3"\n',
        encoding="utf-8",
    )


def _install_pre_rebase_hook(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-rebase"
    guard = repo / "scripts" / "git-hooks" / "pre-rebase-root-guard.ps1"
    hook.write_text(
        f'#!/bin/sh\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "{guard.as_posix()}" "$1" "$2"\n',
        encoding="utf-8",
    )


def test_root_worktree_blocks_impl_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "app" / "worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("root impl change\n", encoding="utf-8")
    _run(["git", "add", "app/worker.py"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_worktree_impl_scope_blocked" in (result.stdout + result.stderr)


def test_root_guard_RIGHT_detects_unstaged_impl_dirty(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "frontend" / "src" / "route.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unstaged root impl change\n", encoding="utf-8")

    result = _run_root_guard(repo, "Dirty")

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "root_worktree_impl_dirty_detected" in output
    assert "frontend/src/route.ts" in output


def test_root_guard_BOUNDARY_allows_operator_docs_dirty(tmp_path):
    repo = _init_repo(tmp_path)
    for name in ("AGENTS.md", "CLAUDE.md"):
        (repo / name).write_text(f"# {name}\n", encoding="utf-8")

    result = _run_root_guard(repo, "Dirty")

    assert result.returncode == 0
    assert "root_worktree_impl_dirty_clean" in (result.stdout + result.stderr)


def test_root_worktree_allows_root_operator_docs(tmp_path):
    repo = _init_repo(tmp_path)
    for name in ("AGENTS.md", "CLAUDE.md"):
        (repo / name).write_text(f"# {name}\n", encoding="utf-8")
        _run(["git", "add", name], repo)

    result = _run_hook(repo)

    assert result.returncode == 0


def test_root_worktree_blocks_mirror_stage_without_merge_head(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("mirror sync change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_sync_merge_subject_mismatch(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("branch impl change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)

    result = _run_hook(
        repo,
        {
            "ROOT_GUARD_DRY_RUN": "1",
            "ROOT_GUARD_MERGE_HEAD": "1",
            "ROOT_GUARD_MERGE_SUBJECT": "impl change",
            "ROOT_GUARD_UNMERGED": "",
        },
    )

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_sync_merge_with_non_mirror_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "app" / "worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("implementation change\n", encoding="utf-8")
    _run(["git", "add", "app/worker.py"], repo)

    result = _run_hook(
        repo,
        {
            "ROOT_GUARD_DRY_RUN": "1",
            "ROOT_GUARD_MERGE_HEAD": "1",
            "ROOT_GUARD_MERGE_SUBJECT": "chore: sync skills and agent files",
            "ROOT_GUARD_UNMERGED": "",
        },
    )

    assert result.returncode != 0
    assert "root_worktree_impl_scope_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_sync_merge_with_mirror_only_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("mirror sync change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)

    result = _run_hook(
        repo,
        {
            "ROOT_GUARD_DRY_RUN": "1",
            "ROOT_GUARD_MERGE_HEAD": "1",
            "ROOT_GUARD_MERGE_SUBJECT": "chore: sync skills and agent files",
            "ROOT_GUARD_UNMERGED": "",
        },
    )

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        (".agents/skills/done/SKILL.md", "modify"),
        (".claude/skills/done/SKILL.md", "delete"),
        (".gemini/agents/plan.md", "modify"),
        (".gemini/agents/new.md", "add"),
    ],
)
def test_root_worktree_blocks_mirror_add_modify_delete_on_main(tmp_path, path, operation):
    repo = _init_repo(tmp_path)
    target = repo / path
    if operation == "delete":
        _run(["git", "rm", path], repo)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{operation} mirror path\n", encoding="utf-8")
        _run(["git", "add", path], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_incident_gemini_agent_files(tmp_path):
    repo = _init_repo(tmp_path)
    for path in (
        ".gemini/agents/ideation.md",
        ".gemini/agents/next.md",
        ".gemini/agents/plan-list.md",
        ".gemini/agents/plan.md",
    ):
        target = repo / path
        target.write_text("incident mirror change\n", encoding="utf-8")
        _run(["git", "add", path], repo)

    result = _run_hook(
        repo,
        {
            "ROOT_GUARD_DRY_RUN": "1",
            "ROOT_GUARD_MERGE_HEAD": "1",
            "ROOT_GUARD_MERGE_SUBJECT": "chore: sync skills and agent files",
            "ROOT_GUARD_UNMERGED": "",
        },
    )

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_sync_merge_with_unmerged_mirror_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("mirror sync change\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], repo)

    result = _run_hook(
        repo,
        {
            "ROOT_GUARD_DRY_RUN": "1",
            "ROOT_GUARD_MERGE_HEAD": "1",
            "ROOT_GUARD_MERGE_SUBJECT": "chore: sync skills and agent files",
            "ROOT_GUARD_UNMERGED": ".claude/skills/done/SKILL.md",
        },
    )

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_commit_ready_merge_subject_mismatch(tmp_path):
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

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


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
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_root_worktree_blocks_task_ledger_stage(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "TODO.md"
    target.write_text("# TODO\n\n- [ ] ledger\n", encoding="utf-8")
    _run(["git", "add", "TODO.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_worktree_impl_scope_blocked" in (result.stdout + result.stderr)


def test_plans_worktree_allows_task_ledger_stage(tmp_path):
    repo = _init_repo(tmp_path)
    plans = repo / ".worktrees" / "plans"
    _run(["git", "worktree", "add", str(plans), "-b", "plans"], repo)

    target = plans / "TODO.md"
    target.write_text("# TODO\n\n- [ ] ledger\n", encoding="utf-8")
    _run(["git", "add", "TODO.md"], plans)

    result = _run_hook(plans)

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


def test_linked_worktree_blocks_mirror_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "impl-root-fence"
    _run(["git", "worktree", "add", str(worktree), "-b", "impl/root-fence"], repo)

    target = worktree / ".claude" / "skills" / "done" / "SKILL.md"
    target.write_text("linked dirty\n", encoding="utf-8")
    _run(["git", "add", ".claude/skills/done/SKILL.md"], worktree)

    result = _run_hook(worktree)

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_linked_worktree_allows_product_scope_stage(tmp_path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "impl-product"
    _run(["git", "worktree", "add", str(worktree), "-b", "impl/product"], repo)

    target = worktree / "app" / "worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("linked product dirty\n", encoding="utf-8")
    _run(["git", "add", "app/worker.py"], worktree)

    result = _run_hook(worktree)

    assert result.returncode == 0


def test_codex_workflow_mirror_edit_blocked_in_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "codex-mirror-edit"
    _run(["git", "worktree", "add", str(worktree), "-b", "codex/mirror-edit"], repo)

    target = worktree / ".agents" / "skills" / "done" / "SKILL.md"
    target.write_text("codex mirror edit\n", encoding="utf-8")
    _run(["git", "add", ".agents/skills/done/SKILL.md"], worktree)

    result = _run_hook(worktree)

    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_github_actions_block_mirror_direct_edits_yaml_parses():
    yaml = pytest.importorskip("yaml")
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "block-mirror-direct-edits.yml"
    )

    loaded = yaml.safe_load(workflow.read_text(encoding="utf-8"))

    assert loaded["name"] == "Block mirror direct edits"
    assert "block-mirror-direct-edits" in loaded["jobs"]


def test_root_non_main_blocks_any_commit(tmp_path):
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "impl/accidental-root"], repo)
    (repo / "TODO.md").write_text("# TODO\n\n- [ ] ledger\n", encoding="utf-8")
    _run(["git", "add", "TODO.md"], repo)

    result = _run_hook(repo)

    assert result.returncode != 0
    assert "root_branch_guard_blocked" in (result.stdout + result.stderr)


def test_root_guard_allows_rebase_transient_detached_head_without_sentinel(tmp_path):
    repo = _init_repo(tmp_path)
    sentinel = repo / ".git" / "root-branch-guard.violation"

    result = _run_root_guard(repo, "PostCheckout", _root_guard_dry_run_env(repo, "HEAD", "1"))

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "root_branch_guard_transient_detached_allowed" in output
    assert not sentinel.exists()


def test_root_guard_blocks_plain_detached_head_without_transient_evidence(tmp_path):
    repo = _init_repo(tmp_path)
    sentinel = repo / ".git" / "root-branch-guard.violation"

    result = _run_root_guard(repo, "PostCheckout", _root_guard_dry_run_env(repo, "HEAD", "0"))

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "root_branch_guard_violation" in output
    assert sentinel.exists()
    assert "branch=HEAD" in sentinel.read_text(encoding="utf-8")


def test_root_guard_blocks_named_branch_even_with_transient_evidence(tmp_path):
    repo = _init_repo(tmp_path)
    sentinel = repo / ".git" / "root-branch-guard.violation"

    result = _run_root_guard(repo, "PostCheckout", _root_guard_dry_run_env(repo, "impl/foo", "1"))

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "root_branch_guard_violation" in output
    assert sentinel.exists()
    assert "branch=impl/foo" in sentinel.read_text(encoding="utf-8")


def test_root_guard_pre_rebase_blocks_root_main_by_default(tmp_path):
    repo = _init_repo(tmp_path)

    result = _run_root_guard(repo, "PreRebase")

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "root_main_rebase_blocked" in output


def test_root_guard_pre_rebase_allows_impl_worktree_branch(tmp_path):
    repo = _init_repo(tmp_path)
    worktree = repo / ".worktrees" / "impl-rebase"
    _run(["git", "worktree", "add", str(worktree), "-b", "impl/rebase"], repo)

    result = _run_root_guard(worktree, "PreRebase")

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "root_main_rebase_guard_clean: not root checkout" in output


def test_pre_rebase_hook_blocks_git_rebase_on_root_main(tmp_path):
    repo = _init_repo(tmp_path)
    _install_pre_rebase_hook(repo)
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _run(["git", "add", "local.txt"], repo)
    _run(["git", "commit", "-m", "local"], repo)

    result = subprocess.run(
        ["git", "rebase", "--force-rebase", "HEAD~1"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "root_main_rebase_blocked" in output


def test_pre_rebase_hook_allows_impl_worktree_rebase(tmp_path):
    repo = _init_repo(tmp_path)
    _install_pre_rebase_hook(repo)
    worktree = repo / ".worktrees" / "impl-rebase"
    _run(["git", "worktree", "add", str(worktree), "-b", "impl/rebase"], repo)
    (worktree / "impl.txt").write_text("impl\n", encoding="utf-8")
    _run(["git", "add", "impl.txt"], worktree)
    _run(["git", "commit", "-m", "impl"], worktree)
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _run(["git", "add", "main.txt"], repo)
    _run(["git", "commit", "-m", "main"], repo)

    result = subprocess.run(
        ["git", "rebase", "main"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_root_guard_real_rebase_transient_detached_head_without_sentinel(tmp_path):
    repo = _init_repo(tmp_path)
    origin = tmp_path / "origin.git"
    upstream = tmp_path / "upstream"
    _run(["git", "init", "--bare", str(origin)], tmp_path)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)
    _run(["git", "clone", "-b", "main", str(origin), str(upstream)], tmp_path)
    _run(["git", "config", "user.name", "root-worktree-smoke"], upstream)
    _run(["git", "config", "user.email", "root-worktree-smoke@example.com"], upstream)

    (upstream / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run(["git", "add", "remote.txt"], upstream)
    _run(["git", "commit", "-m", "remote change"], upstream)
    _run(["git", "push", "origin", "main"], upstream)

    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _run(["git", "add", "local.txt"], repo)
    _run(["git", "commit", "-m", "local change"], repo)
    _install_post_checkout_hook(repo)

    rebase = subprocess.run(
        ["git", "pull", "--rebase", "origin", "main"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert rebase.returncode == 0, rebase.stdout + rebase.stderr
    assert not (repo / ".git" / "root-branch-guard.violation").exists()


def test_root_guard_real_root_branch_switch_still_writes_sentinel(tmp_path):
    repo = _init_repo(tmp_path)
    _install_post_checkout_hook(repo)

    result = subprocess.run(
        ["git", "switch", "-c", "impl/accidental-root"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout + result.stderr
    assert "root_branch_guard_violation" in output
    sentinel = repo / ".git" / "root-branch-guard.violation"
    assert sentinel.exists()
    assert "branch=impl/accidental-root" in sentinel.read_text(encoding="utf-8")


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
