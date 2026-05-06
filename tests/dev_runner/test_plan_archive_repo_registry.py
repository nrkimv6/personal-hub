"""Plan Archive repo registry contracts."""

import json

from app.modules.dev_runner.services.plan_archive_repo_registry import (
    PlanArchiveRepoRegistry,
    normalize_repo_key,
)


def test_repo_registry_right_loads_projects(tmp_path):
    monitor = tmp_path / "monitor-page"
    plans = monitor / ".worktrees" / "plans"
    wtools = tmp_path / "wtools"
    child = tmp_path / "child-tool"
    for root in [monitor, plans, wtools, child]:
        root.mkdir(parents=True)
        (root / ".git").mkdir()
    config_path = wtools / ".claude" / "projects.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"projects": [{"name": "Child Tool", "path": str(child)}]}),
        encoding="utf-8",
    )

    registry = PlanArchiveRepoRegistry(
        project_root=monitor,
        wtools_base_dir=wtools,
        project_config_paths=[config_path],
    )

    repos = registry.list_repos()

    assert [repo.repo_key for repo in repos] == [
        "monitor-page",
        "monitor-page-plans",
        "wtools",
        "child-tool",
    ]
    assert all(repo.status == "ready" for repo in repos)


def test_repo_registry_boundary_marks_missing_or_non_git_skipped(tmp_path):
    monitor = tmp_path / "monitor-page"
    wtools = tmp_path / "wtools"
    monitor.mkdir()
    (monitor / ".git").mkdir()
    wtools.mkdir()
    config_path = tmp_path / "projects.json"
    config_path.write_text(
        json.dumps({"projects": [{"name": "Missing Repo", "path": str(tmp_path / "missing")}]}),
        encoding="utf-8",
    )

    registry = PlanArchiveRepoRegistry(
        project_root=monitor,
        wtools_base_dir=wtools,
        project_config_paths=[config_path],
    )

    repos = registry.list_repos()

    skipped = {repo.repo_key: repo.reason for repo in repos if repo.status == "skipped"}
    assert skipped["monitor-page-plans"] == "repo root does not exist"
    assert skipped["wtools"] == "not a git repository"
    assert skipped["missing-repo"] == "repo root does not exist"


def test_normalize_repo_key_right_stable_slug(tmp_path):
    assert normalize_repo_key("Child Tool!", tmp_path) == "child-tool"
