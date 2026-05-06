"""Correct runner git metadata from Redis snapshots and live git state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Literal

from app.modules.dev_runner.services.git_utils import check_branch_exists

RunnerMetadataState = bool | Literal["unknown"]
RunnerGitMetadataConfidence = Literal["redis", "git_verified", "git_missing"]


@dataclass(frozen=True)
class RunnerGitMetadata:
    branch: str | None
    worktree_path: str | None
    branch_exists: RunnerMetadataState
    worktree_exists: RunnerMetadataState
    current_head: str | None = None
    confidence: RunnerGitMetadataConfidence = "redis"


def _coerce_metadata_state(value: object) -> RunnerMetadataState:
    if isinstance(value, bool):
        return value
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return "unknown"


def _git_stdout(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _current_head(cwd: Path) -> str | None:
    return _git_stdout(cwd, "rev-parse", "HEAD")


def build_runner_git_metadata(
    *,
    branch: str | None,
    worktree_path: str | None,
    redis_branch_exists: object = "unknown",
    redis_worktree_exists: object = "unknown",
    repo_cwd: str | None = None,
) -> RunnerGitMetadata:
    """Return git metadata after reconciling Redis hints with live git evidence."""

    branch_exists = _coerce_metadata_state(redis_branch_exists)
    worktree_exists = _coerce_metadata_state(redis_worktree_exists)
    confidence: RunnerGitMetadataConfidence = "redis"
    current_head: str | None = None

    git_cwd: Path | None = None
    if worktree_path:
        worktree = Path(worktree_path)
        if not worktree.is_dir():
            return RunnerGitMetadata(
                branch=branch,
                worktree_path=worktree_path,
                branch_exists=False if branch else branch_exists,
                worktree_exists=False,
                current_head=None,
                confidence="git_missing",
            )
        git_cwd = worktree
        worktree_exists = True
    elif repo_cwd:
        git_cwd = Path(repo_cwd)

    if git_cwd is not None:
        current_head = _current_head(git_cwd)
        if branch:
            if check_branch_exists(branch, cwd=str(git_cwd)):
                branch_exists = True
                confidence = "git_verified"
            else:
                branch_exists = False
                confidence = "git_missing"

    return RunnerGitMetadata(
        branch=branch,
        worktree_path=worktree_path,
        branch_exists=branch_exists,
        worktree_exists=worktree_exists,
        current_head=current_head,
        confidence=confidence,
    )
