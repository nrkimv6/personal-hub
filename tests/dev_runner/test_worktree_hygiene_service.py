from __future__ import annotations

import shutil
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path

from app.modules.dev_runner.services.worktree_hygiene_service import (
    INTEREST_KEEP_SYSTEM,
    INTEREST_NEEDS_OWNER_REVIEW,
    INTEREST_STALE_CLEANUP_CANDIDATE,
    INTEREST_STALE_LOCKED_REVIEW,
    WorktreeHygieneService,
    render_worktree_hygiene_report,
)


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
    plans = repo / ".worktrees" / "plans"
    _git(repo, "worktree", "add", str(plans), "-b", "plans")
    _git(repo, "worktree", "lock", str(plans), "--reason", "plans SSOT")
    return repo


def _add_worktree(repo: Path, branch: str, folder: str) -> Path:
    path = repo / ".worktrees" / folder
    path.parent.mkdir(exist_ok=True)
    _git(repo, "worktree", "add", str(path), "-b", branch)
    return path


def _write_plan(repo: Path, *, branch: str, name: str, status: str = "구현중", archived: bool = False, extra: str = "") -> Path:
    base = repo / ".worktrees" / "plans" / "docs" / ("archive" if archived else "plan")
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(
        "\n".join(
            [
                "# plan title",
                f"> 상태: {status}",
                f"> branch: {branch}",
                f"> worktree: .worktrees/{branch.split('/', 1)[-1]}",
                "> 진행률: 1/1 (100%)",
                "",
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return path


def _by_branch(snapshot, branch: str):
    return next(item for item in snapshot.registered_worktrees if item.branch == branch)


def test_collect_registered_worktrees_R_clean_ahead_zero_archived_candidate(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/archived-clean"
    _add_worktree(repo, branch, "archived-clean")
    _write_plan(repo, branch=branch, name="archived.md", status="구현완료", archived=True)

    snapshot = WorktreeHygieneService(repo).collect()

    item = _by_branch(snapshot, branch)
    assert item.ahead == 0
    assert item.archived is True
    assert item.interest_level == INTEREST_STALE_CLEANUP_CANDIDATE
    assert item.cleanup_recommendation == "registered_worktree_cleanup_candidate"


def test_collect_registered_worktrees_B_locked_plans_never_cleanable(tmp_path: Path):
    repo = _init_repo(tmp_path)

    snapshot = WorktreeHygieneService(repo).collect()

    plans = next(item for item in snapshot.registered_worktrees if item.is_plans)
    assert plans.locked is True
    assert plans.interest_level == INTEREST_KEEP_SYSTEM
    assert plans.cleanup_recommendation == "keep_system"


def test_collect_residue_dirs_E_git_marker_registered_path_excluded(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/registered"
    registered = _add_worktree(repo, branch, "registered")
    stray = repo / ".worktrees" / "stray-git-marker"
    stray.mkdir(parents=True)
    (stray / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")

    snapshot = WorktreeHygieneService(repo).collect()

    residue_paths = {item.path for item in snapshot.residues}
    assert registered.as_posix() not in residue_paths
    assert any(item.kind == "git_marker_unregistered" for item in snapshot.residues)


def test_interest_level_R_locked_clean_fresh_requires_owner_review_not_stale(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/locked-clean"
    worktree = _add_worktree(repo, branch, "locked-clean")
    _git(repo, "worktree", "lock", str(worktree), "--reason", "manual owner")

    snapshot = WorktreeHygieneService(repo).collect()

    item = _by_branch(snapshot, branch)
    assert item.interest_level == INTEREST_NEEDS_OWNER_REVIEW
    assert item.cleanup_recommendation == "review_lock_before_cleanup"


def test_interest_level_B_locked_clean_old_requires_review_not_auto_delete(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/locked-clean-old"
    worktree = _add_worktree(repo, branch, "locked-clean-old")
    _git(repo, "worktree", "lock", str(worktree), "--reason", "manual owner")
    old_timestamp = (datetime.now() - timedelta(days=20)).timestamp()
    os.utime(worktree, (old_timestamp, old_timestamp))

    snapshot = WorktreeHygieneService(repo).collect(stale_worktree_days=14)

    item = _by_branch(snapshot, branch)
    assert item.interest_level == INTEREST_STALE_LOCKED_REVIEW
    assert item.cleanup_recommendation == "review_lock_before_cleanup"


def test_collect_residue_dirs_R_nested_pytest_cache_only_is_cache_residue(tmp_path: Path):
    repo = _init_repo(tmp_path)
    cache_file = repo / ".worktrees" / "post-remove" / "common" / "tools" / ".pytest_cache" / "README.md"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("cache\n", encoding="utf-8")

    snapshot = WorktreeHygieneService(repo).collect()

    residue = next(item for item in snapshot.residues if item.path.endswith("post-remove"))
    assert residue.kind == "cache_only_residue"
    assert residue.source_file_count == 0
    assert residue.action_hint == "safe_delete_candidate"


def test_collect_registered_worktrees_E_missing_registered_path_reported_as_stale_metadata(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/missing"
    worktree = _add_worktree(repo, branch, "missing")
    shutil.rmtree(worktree)

    snapshot = WorktreeHygieneService(repo).collect()

    item = _by_branch(snapshot, branch)
    assert item.exists is False
    assert item.cleanup_recommendation == "git_worktree_prune_review"


def test_plan_linked_cleanup_R_clean_ahead_zero_requires_unimplemented_or_discard_decision(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/active-clean"
    _add_worktree(repo, branch, "active-clean")
    _write_plan(repo, branch=branch, name="active.md", status="구현중")

    snapshot = WorktreeHygieneService(repo).collect()

    item = _by_branch(snapshot, branch)
    assert item.interest_level == INTEREST_NEEDS_OWNER_REVIEW
    assert item.required_plan_update == "active_plan_cleanup_outcome_required"
    assert item.cleanup_recommendation == "blocked_plan_update_required"


def test_plan_linked_cleanup_E_archive_plan_requires_no_plan_mutation(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/archive-clean"
    _add_worktree(repo, branch, "archive-clean")
    _write_plan(repo, branch=branch, name="archive.md", status="구현완료", archived=True)

    snapshot = WorktreeHygieneService(repo).collect()

    item = _by_branch(snapshot, branch)
    assert item.required_plan_update == "none"
    assert item.plan_status_action == "already_archived"


def test_collect_plans_hygiene_R_logs_gitignore_warning(tmp_path: Path):
    repo = _init_repo(tmp_path)
    logs_dir = repo / ".worktrees" / "plans" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "run.log").write_text("runtime\n", encoding="utf-8")

    snapshot = WorktreeHygieneService(repo).collect()

    assert snapshot.plans.logs_gitignore_warning is True
    assert any("logs/" in item for item in snapshot.plans.untracked_runtime)


def test_collect_plans_hygiene_R_modified_archive_path_preserves_first_character(tmp_path: Path):
    repo = _init_repo(tmp_path)
    plans = repo / ".worktrees" / "plans"
    archive_file = plans / "docs" / "archive" / "touched.md"
    archive_file.parent.mkdir(parents=True)
    archive_file.write_text("before\n", encoding="utf-8")
    _git(plans, "add", "docs/archive/touched.md")
    _git(plans, "commit", "-m", "seed archive")
    archive_file.write_text("after\n", encoding="utf-8")

    snapshot = WorktreeHygieneService(repo).collect()

    assert "docs/archive/touched.md" in snapshot.plans.archive_changes
    assert "ocs/archive/touched.md" not in snapshot.plans.policy_changes


def test_collect_plan_header_drift_R_missing_worktree_for_active_header(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write_plan(repo, branch="impl/missing-header", name="missing-header.md", status="구현중")

    snapshot = WorktreeHygieneService(repo).collect()

    assert snapshot.plans.header_drifts
    assert snapshot.plans.header_drifts[0]["reason"] == "active_header_worktree_missing"


def test_render_report_R_includes_registered_residue_and_drift_tables(tmp_path: Path):
    repo = _init_repo(tmp_path)
    _write_plan(repo, branch="impl/missing-header", name="missing-header.md", status="구현중")
    (repo / ".worktrees" / "api_gate_live_coverage.patch").write_text("patch\n", encoding="utf-8")
    snapshot = WorktreeHygieneService(repo).collect()

    report = render_worktree_hygiene_report(snapshot)

    assert "## 등록 Worktree" in report
    assert "## Residue" in report
    assert "## Header Drift" in report
    assert "api_gate_live_coverage.patch" in report


def test_render_report_R_archive_gap_remains_report_only_without_tracking_section(tmp_path: Path):
    repo = _init_repo(tmp_path)
    branch = "impl/archive-gap"
    wt = _add_worktree(repo, branch, "archive-gap")
    (wt / "change.txt").write_text("change\n", encoding="utf-8")
    _git(wt, "add", "change.txt")
    _git(wt, "commit", "-m", "change")
    _write_plan(repo, branch=branch, name="archive-gap.md", status="구현완료", archived=True)

    snapshot = WorktreeHygieneService(repo).collect()
    report = render_worktree_hygiene_report(snapshot)

    assert not hasattr(snapshot, "tracking_candidates")
    assert "Tracking Candidates" not in report
    assert "archive_merge_gap" not in report
