from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "staged-sync-contract"], repo)
    _run(["git", "config", "user.email", "staged-sync-contract@example.com"], repo)

    (repo / ".agents" / "skills" / "done").mkdir(parents=True)
    (repo / ".claude" / "skills" / "done").mkdir(parents=True)
    (repo / "scripts" / "git-hooks").mkdir(parents=True)
    (repo / ".agents" / "skills" / "done" / "SKILL.md").write_text("base agents\n", encoding="utf-8")
    (repo / ".claude" / "skills" / "done" / "SKILL.md").write_text("base claude\n", encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")

    src_root = Path(__file__).resolve().parents[2]
    for name in ("pre-commit-plans-block.ps1", "root-branch-guard.ps1"):
        shutil.copy2(
            src_root / "scripts" / "git-hooks" / name,
            repo / "scripts" / "git-hooks" / name,
        )

    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _run_guard(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"),
        ],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_staged_only_mirror_dirty_is_not_hidden_by_empty_worktree_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / ".agents" / "skills" / "done" / "SKILL.md"
    target.write_text("stale sync snapshot\n", encoding="utf-8")
    _run(["git", "add", ".agents/skills/done/SKILL.md"], repo)

    unstaged = _run(["git", "diff", "--name-only"], repo).stdout.strip()
    staged = _run(["git", "diff", "--cached", "--name-only"], repo).stdout.strip()
    result = _run_guard(repo)

    assert unstaged == ""
    assert staged == ".agents/skills/done/SKILL.md"
    assert result.returncode != 0
    assert "mirror_surface_direct_edit_blocked" in (result.stdout + result.stderr)


def test_backup_ref_preserves_staged_snapshot_before_index_cleanup(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    target = repo / "README.md"
    target.write_text("staged residue\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)

    tree_sha = _run(["git", "write-tree"], repo).stdout.strip()
    commit_sha = _run(
        ["git", "commit-tree", tree_sha, "-p", "HEAD", "-m", "backup: staged residue"],
        repo,
    ).stdout.strip()
    _run(["git", "branch", "backup/staged-residue", commit_sha], repo)
    _run(["git", "reset", "--mixed", "HEAD"], repo)

    current = (repo / "README.md").read_text(encoding="utf-8")
    backup = _run(["git", "show", "backup/staged-residue:README.md"], repo).stdout

    assert current == "staged residue\n"
    assert backup == "staged residue\n"


def test_stale_sync_blob_can_be_classified_against_known_sync_commits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    path = ".claude/skills/done/SKILL.md"
    target = repo / path

    target.write_text("old sync\n", encoding="utf-8")
    _run(["git", "add", path], repo)
    _run(["git", "commit", "-m", "chore: sync skills and agent files"], repo)
    old_sync = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()

    target.write_text("new sync\n", encoding="utf-8")
    _run(["git", "add", path], repo)
    _run(["git", "commit", "-m", "chore: sync skills and agent files"], repo)
    new_sync = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()

    target.write_text("old sync\n", encoding="utf-8")
    _run(["git", "add", path], repo)
    staged_blob = _run(["git", "rev-parse", f":{path}"], repo).stdout.strip()
    old_blob = _run(["git", "rev-parse", f"{old_sync}:{path}"], repo).stdout.strip()
    new_blob = _run(["git", "rev-parse", f"{new_sync}:{path}"], repo).stdout.strip()

    assert staged_blob == old_blob
    assert staged_blob != new_blob


def test_non_ff_sync_state_is_detected_without_local_merge(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "--initial-branch=main", str(origin)], tmp_path)

    work = tmp_path / "work"
    _run(["git", "clone", str(origin), str(work)], tmp_path)
    _run(["git", "config", "user.name", "local"], work)
    _run(["git", "config", "user.email", "local@example.com"], work)
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "README.md"], work)
    _run(["git", "commit", "-m", "base"], work)
    _run(["git", "push", "origin", "main"], work)

    remote_work = tmp_path / "remote-work"
    _run(["git", "clone", str(origin), str(remote_work)], tmp_path)
    _run(["git", "config", "user.name", "remote"], remote_work)
    _run(["git", "config", "user.email", "remote@example.com"], remote_work)

    (work / "local.txt").write_text("local\n", encoding="utf-8")
    _run(["git", "add", "local.txt"], work)
    _run(["git", "commit", "-m", "local ahead"], work)

    (remote_work / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run(["git", "add", "remote.txt"], remote_work)
    _run(["git", "commit", "-m", "remote ahead"], remote_work)
    _run(["git", "push", "origin", "main"], remote_work)

    _run(["git", "fetch", "origin", "main"], work)
    head_is_origin_ancestor = _run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], work, check=False)
    origin_is_head_ancestor = _run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], work, check=False)
    status = _run(["git", "status", "--porcelain=v2", "--branch"], work).stdout

    assert head_is_origin_ancestor.returncode == 1
    assert origin_is_head_ancestor.returncode == 1
    assert "branch.ab +1 -1" in status
