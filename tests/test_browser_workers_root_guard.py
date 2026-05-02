from pathlib import Path

from scripts.services.browser_worker_runtime.cli import main as cli_main
from scripts.services.browser_worker_runtime.runtime import (
    RepoCheckoutError,
    assert_repo_root_checkout,
)


def test_assert_repo_root_checkout_accepts_root_checkout_R(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    assert_repo_root_checkout(project_root=repo, cwd=repo)


def test_assert_repo_root_checkout_rejects_linked_worktree_E(tmp_path: Path):
    worktree = tmp_path / "repo" / ".worktrees" / "impl-test"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../.git/worktrees/impl-test", encoding="utf-8")

    try:
        assert_repo_root_checkout(project_root=worktree, cwd=worktree)
    except RepoCheckoutError as exc:
        message = str(exc)
    else:
        raise AssertionError("linked worktree checkout should be rejected")

    assert "root checkout" in message
    assert str(worktree.resolve()) in message


def test_assert_repo_root_checkout_rejects_root_script_from_worktree_cwd_E(tmp_path: Path):
    repo = tmp_path / "repo"
    cwd = repo / ".worktrees" / "impl-test"
    cwd.mkdir(parents=True)
    (repo / ".git").mkdir()

    try:
        assert_repo_root_checkout(project_root=repo, cwd=cwd)
    except RepoCheckoutError as exc:
        message = str(exc)
    else:
        raise AssertionError("root script launched from .worktrees cwd should be rejected")

    assert "current checkout=" in message
    assert "allowed root checkout=" in message


def test_browser_workers_main_rejects_worktree_dispatch_E(monkeypatch, capsys):
    calls: list[str] = []

    class FakeManager:
        def __init__(self):
            calls.append("init")

    def reject_checkout():
        raise RepoCheckoutError("service commands must be run from the root checkout only")

    monkeypatch.setattr(
        "scripts.services.browser_worker_runtime.cli.assert_repo_root_checkout",
        reject_checkout,
    )

    result = cli_main(FakeManager, ["status"])

    assert result == 1
    assert calls == []
    assert "root checkout" in capsys.readouterr().err
