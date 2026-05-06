from __future__ import annotations

from pathlib import Path
import subprocess

from app.modules.dev_runner.services.runner_git_metadata import build_runner_git_metadata
from app.modules.dev_runner.services.runner_read_model import build_runner_read_model


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(path, "init")
    _run_git(path, "config", "user.email", "test@example.com")
    _run_git(path, "config", "user.name", "Test User")
    (path / "file.txt").write_text("initial\n", encoding="utf-8")
    _run_git(path, "add", "file.txt")
    _run_git(path, "commit", "-m", "initial")
    return path


def test_checked_out_branch_marker_is_detected_from_show_ref(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _run_git(repo, "checkout", "-b", "impl/read-model")
    _run_git(repo, "checkout", "-")
    linked_worktree = tmp_path / "linked"
    _run_git(repo, "worktree", "add", str(linked_worktree), "impl/read-model")

    assert "+ impl/read-model" in _run_git(repo, "branch", "--list", "impl/read-model")

    metadata = build_runner_git_metadata(
        branch="impl/read-model",
        worktree_path=str(linked_worktree),
        redis_branch_exists="false",
        redis_worktree_exists="true",
    )

    assert metadata.branch_exists is True
    assert metadata.worktree_exists is True
    assert metadata.confidence == "git_verified"


def test_redis_false_branch_exists_is_corrected_when_git_ref_exists(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _run_git(repo, "checkout", "-b", "impl/stale-redis")

    metadata = build_runner_git_metadata(
        branch="impl/stale-redis",
        worktree_path=str(repo),
        redis_branch_exists=False,
        redis_worktree_exists=True,
    )

    assert metadata.branch_exists is True
    assert metadata.confidence == "git_verified"
    assert metadata.current_head


def test_missing_worktree_returns_git_missing_confidence(tmp_path):
    missing_worktree = tmp_path / "missing"

    metadata = build_runner_git_metadata(
        branch="impl/missing",
        worktree_path=str(missing_worktree),
        redis_branch_exists=True,
        redis_worktree_exists=True,
    )

    assert metadata.branch_exists is False
    assert metadata.worktree_exists is False
    assert metadata.current_head is None
    assert metadata.confidence == "git_missing"


def test_runner_read_model_corrects_stale_redis_branch_hint(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _run_git(repo, "checkout", "-b", "impl/read-model-stale")

    model = build_runner_read_model(
        runner_id="runner-read-model-1",
        running=False,
        merge_status="approval_required",
        exit_reason="completed",
        branch="impl/read-model-stale",
        worktree_path=str(repo),
        redis_branch_exists=False,
        redis_worktree_exists=True,
    )

    assert model.branch_exists is True
    assert model.worktree_exists is True
    assert model.git is not None
    assert model.git.confidence == "git_verified"
