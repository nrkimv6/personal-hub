from __future__ import annotations

import subprocess
from pathlib import Path

from app.modules.dev_runner.services.worktree_hygiene_service import WorktreeHygieneService


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(repo),
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "worktree", "add", str(repo / ".worktrees" / "plans"), "-b", "plans")
    return repo


def _scenario_repo(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path)
    _git(repo, "worktree", "add", str(repo / ".worktrees" / "impl-live"), "-b", "impl/live")
    empty = repo / ".worktrees" / "empty-residue"
    empty.mkdir(parents=True)
    cache_file = repo / ".worktrees" / "cache-residue" / "nested" / ".pytest_cache" / "README.md"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache\n", encoding="utf-8")
    source_file = repo / ".worktrees" / "source-residue" / "app" / "main.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("print('keep')\n", encoding="utf-8")
    (repo / ".worktrees" / "api_gate_live_coverage.patch").write_text("patch\n", encoding="utf-8")
    logs = repo / ".worktrees" / "plans" / "logs"
    logs.mkdir(parents=True)
    (logs / "run.log").write_text("runtime\n", encoding="utf-8")
    return repo


def test_collector_separates_registered_worktree_residue_and_file_artifact(tmp_path: Path):
    repo = _scenario_repo(tmp_path)

    snapshot = WorktreeHygieneService(repo).collect(auto_delete_residue=False)

    branches = {item.branch for item in snapshot.registered_worktrees}
    residue_kinds = {item.kind for item in snapshot.residues}
    assert "impl/live" in branches
    assert "empty_residue" in residue_kinds
    assert "cache_only_residue" in residue_kinds
    assert "source_residue" in residue_kinds
    assert "file_artifact" in residue_kinds
    assert snapshot.plans.untracked_runtime


def test_report_only_never_deletes_residue(tmp_path: Path):
    repo = _scenario_repo(tmp_path)

    snapshot = WorktreeHygieneService(repo).collect(auto_delete_residue=False, residue_retention_days=0)

    assert snapshot.statistics["removed_residue_count"] == 0
    assert (repo / ".worktrees" / "empty-residue").exists()
    assert (repo / ".worktrees" / "cache-residue").exists()


def test_auto_delete_residue_removes_only_source_free_retained_dirs(tmp_path: Path):
    repo = _scenario_repo(tmp_path)

    snapshot = WorktreeHygieneService(repo).collect(auto_delete_residue=True, residue_retention_days=0)

    removed = {item.path for item in snapshot.residues if item.delete_status == "removed"}
    assert any(path.endswith("empty-residue") for path in removed)
    assert any(path.endswith("cache-residue") for path in removed)
    assert (repo / ".worktrees" / "source-residue").exists()
    assert (repo / ".worktrees" / "api_gate_live_coverage.patch").exists()
