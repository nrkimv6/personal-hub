from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.modules.dev_runner.routes import plans as plans_route


def _registered(path: Path, path_type: str = "plan") -> SimpleNamespace:
    return SimpleNamespace(path=str(path), path_type=path_type, type="folder", plan_count=1)


def test_get_plan_storage_roots_status_right_returns_multiple_roots(monkeypatch, tmp_path):
    repo_a = tmp_path / "monitor-page"
    repo_b = tmp_path / "wtools"
    (repo_a / ".worktrees" / "plans").mkdir(parents=True)
    (repo_b / ".worktrees" / "plans").mkdir(parents=True)

    class FakePlanService:
        @staticmethod
        def list_registered_paths():
            return [
                _registered(repo_a / ".worktrees" / "plans" / "docs" / "plan"),
                _registered(repo_b / ".worktrees" / "plans" / "docs" / "archive", "archive"),
            ]

    class FakeHygieneService:
        def __init__(self, repo_root):
            self.repo_root = Path(repo_root)

        def collect(self):
            if self.repo_root.name == "monitor-page":
                plans = SimpleNamespace(
                    exists=True,
                    branch="plans",
                    upstream="origin/plans",
                    git_status=[" M docs/plan/a.md", "?? docs/archive/b.md"],
                    docs_changes=["docs/plan/a.md"],
                    archive_changes=["docs/archive/b.md"],
                    policy_changes=[],
                    upstream_ahead=2,
                    upstream_behind=0,
                    push_needed=True,
                )
            else:
                plans = SimpleNamespace(
                    exists=True,
                    branch="plans",
                    upstream="origin/plans",
                    git_status=[],
                    docs_changes=[],
                    archive_changes=[],
                    policy_changes=[],
                    upstream_ahead=0,
                    upstream_behind=1,
                    push_needed=False,
                )
            return SimpleNamespace(collected_at="2026-05-05T12:00:00", plans=plans)

    monkeypatch.setattr(plans_route, "plan_service", FakePlanService())
    monkeypatch.setattr(plans_route, "WorktreeHygieneService", FakeHygieneService)

    response = plans_route._collect_plan_storage_roots_status_sync()

    assert response.total == 2
    assert [root.project for root in response.roots] == ["monitor-page", "wtools"]
    first = response.roots[0]
    assert first.status == "dirty"
    assert first.dirty_count == 2
    assert first.docs_changes_count == 1
    assert first.archive_changes_count == 1
    assert first.ahead == 2
    assert first.push_needed is True
    assert first.representative_changes[0].path == "docs/plan/a.md"
    assert response.push_needed_count == 1


def test_get_plan_storage_roots_status_error_missing_one_root_graceful(monkeypatch, tmp_path):
    repo_exists = tmp_path / "monitor-page"
    repo_missing = tmp_path / "external"
    (repo_exists / ".worktrees" / "plans").mkdir(parents=True)

    class FakePlanService:
        @staticmethod
        def list_registered_paths():
            return [
                _registered(repo_exists / ".worktrees" / "plans" / "docs" / "plan"),
                _registered(repo_missing / ".worktrees" / "plans" / "docs" / "plan"),
            ]

    class FakeHygieneService:
        def __init__(self, repo_root):
            self.repo_root = Path(repo_root)

        def collect(self):
            plans = SimpleNamespace(
                exists=True,
                branch="plans",
                upstream=None,
                git_status=[],
                docs_changes=[],
                archive_changes=[],
                policy_changes=[],
                upstream_ahead=0,
                upstream_behind=0,
                push_needed=False,
            )
            return SimpleNamespace(collected_at="2026-05-05T12:00:00", plans=plans)

    monkeypatch.setattr(plans_route, "plan_service", FakePlanService())
    monkeypatch.setattr(plans_route, "WorktreeHygieneService", FakeHygieneService)

    response = plans_route._collect_plan_storage_roots_status_sync()

    assert response.total == 2
    by_project = {root.project: root for root in response.roots}
    assert by_project["monitor-page"].status == "clean"
    assert by_project["external"].exists is False
    assert by_project["external"].status == "missing"


def _run_git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout.strip()


def _init_repo_with_plans_worktree(repo_root: Path, *, with_upstream: bool) -> Path:
    repo_root.mkdir(parents=True)
    _run_git(repo_root, "init", "-b", "main")
    _run_git(repo_root, "config", "user.email", "tests@example.invalid")
    _run_git(repo_root, "config", "user.name", "Tests")
    (repo_root / "README.md").write_text("# test\n", encoding="utf-8")
    _run_git(repo_root, "add", "README.md")
    _run_git(repo_root, "commit", "-m", "init")
    _run_git(repo_root, "branch", "plans")
    plans_worktree = repo_root / ".worktrees" / "plans"
    _run_git(repo_root, "worktree", "add", str(plans_worktree), "plans")
    _run_git(plans_worktree, "config", "user.email", "tests@example.invalid")
    _run_git(plans_worktree, "config", "user.name", "Tests")
    (plans_worktree / "docs" / "plan").mkdir(parents=True)
    (plans_worktree / "docs" / "archive").mkdir(parents=True)
    (plans_worktree / "docs" / "plan" / "2026-05-05_a.md").write_text("# a\n", encoding="utf-8")
    _run_git(plans_worktree, "add", "docs/plan/2026-05-05_a.md")
    _run_git(plans_worktree, "commit", "-m", "seed plans")

    if with_upstream:
        origin = repo_root.parent / f"{repo_root.name}.git"
        _run_git(repo_root.parent, "init", "--bare", str(origin))
        _run_git(repo_root, "remote", "add", "origin", str(origin))
        _run_git(repo_root, "push", "-u", "origin", "main")
        _run_git(plans_worktree, "push", "-u", "origin", "plans")
        (plans_worktree / "docs" / "plan" / "ahead.md").write_text("# ahead\n", encoding="utf-8")
        _run_git(plans_worktree, "add", "docs/plan/ahead.md")
        _run_git(plans_worktree, "commit", "-m", "ahead plans")

    return plans_worktree


def test_get_plan_storage_roots_status_real_git_dirty_ahead_and_missing_upstream(monkeypatch, tmp_path):
    repo_a = tmp_path / "monitor-page"
    repo_b = tmp_path / "wtools"
    plans_a = _init_repo_with_plans_worktree(repo_a, with_upstream=True)
    plans_b = _init_repo_with_plans_worktree(repo_b, with_upstream=False)
    (plans_a / "docs" / "plan" / "dirty.md").write_text("# dirty\n", encoding="utf-8")
    (plans_a / "docs" / "archive" / "archived.md").write_text("# archived\n", encoding="utf-8")

    class FakePlanService:
        @staticmethod
        def list_registered_paths():
            return [
                _registered(plans_a / "docs" / "plan"),
                _registered(plans_a / "docs" / "archive", "archive"),
                _registered(plans_b / "docs" / "plan"),
            ]

    monkeypatch.setattr(plans_route, "plan_service", FakePlanService())

    response = plans_route._collect_plan_storage_roots_status_sync()

    by_project = {root.project: root for root in response.roots}
    assert by_project["monitor-page"].dirty_count == 2
    assert by_project["monitor-page"].docs_changes_count == 1
    assert by_project["monitor-page"].archive_changes_count == 1
    assert by_project["monitor-page"].ahead == 1
    assert by_project["monitor-page"].push_needed is True
    assert by_project["wtools"].exists is True
    assert by_project["wtools"].branch == "plans"
    assert by_project["wtools"].upstream is None
