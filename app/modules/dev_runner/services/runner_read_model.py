"""Runner read model assembly for dev-runner API and SSE payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import PROJECT_ROOT
from app.modules.dev_runner.services.runner_git_metadata import (
    RunnerGitMetadata,
    build_runner_git_metadata,
)

RunnerMetadataState = bool | Literal["unknown"]


@dataclass(frozen=True)
class RunnerReadModel:
    """Shared read model for runner state.

    Priority contract (enforced by build_display_state):
      merge_status=approval_required overrides running=False → display is "approval_required",
      not "stopped". Callers must not short-circuit on running=False alone.
    """

    runner_id: str
    running: bool
    merge_status: str | None
    exit_reason: str | None
    remaining_post_merge_tasks: int = 0
    merge_evidence_missing: bool = False
    git: RunnerGitMetadata | None = None

    @property
    def is_approval_required(self) -> bool:
        return self.merge_status == "approval_required"

    @property
    def branch_exists(self) -> RunnerMetadataState:
        return self.git.branch_exists if self.git else "unknown"

    @property
    def worktree_exists(self) -> RunnerMetadataState:
        return self.git.worktree_exists if self.git else "unknown"


def build_runner_read_model(
    *,
    runner_id: str,
    running: bool,
    merge_status: str | None,
    exit_reason: str | None,
    branch: str | None = None,
    worktree_path: str | None = None,
    redis_branch_exists: object = "unknown",
    redis_worktree_exists: object = "unknown",
    remaining_post_merge_tasks: int | None = None,
    merge_evidence_missing: bool | None = None,
    repo_cwd: str | None = None,
) -> RunnerReadModel:
    """Build the shared read model used by list, single-runner, and SSE surfaces."""

    git = build_runner_git_metadata(
        branch=branch,
        worktree_path=worktree_path,
        redis_branch_exists=redis_branch_exists,
        redis_worktree_exists=redis_worktree_exists,
        repo_cwd=repo_cwd or str(PROJECT_ROOT),
    )
    return RunnerReadModel(
        runner_id=runner_id,
        running=running,
        merge_status=merge_status,
        exit_reason=exit_reason,
        remaining_post_merge_tasks=int(remaining_post_merge_tasks or 0),
        merge_evidence_missing=bool(merge_evidence_missing),
        git=git,
    )
