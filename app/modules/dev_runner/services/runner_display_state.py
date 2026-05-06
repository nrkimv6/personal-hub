"""Display-state policy for dev-runner runners.

Priority matrix:
1. Explicit merge failures win over process completion (`merge_status=error/conflict/test_failed`).
2. `approval_required` hides stale branch badges and asks for user action.
3. Unfinished post-merge tasks prevent a plain completed label.
4. Running and successful merge states are displayed only after the above blockers.
5. Git stale hints are secondary labels, not primary lifecycle state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.dev_runner.services.runner_read_model import RunnerReadModel

RunnerDisplaySeverity = Literal["info", "warn", "error", "approval", "success", "muted"]


@dataclass(frozen=True)
class RunnerDisplayState:
    state: str
    label: str
    severity: RunnerDisplaySeverity
    secondary: str | None = None
    hide_stale_branch_badge: bool = False


def _secondary_stale_label(model: RunnerReadModel) -> str | None:
    if model.worktree_exists is False:
        return "삭제된 worktree"
    if model.branch_exists is False:
        return "branch 없음"
    return None


def build_display_state(model: RunnerReadModel) -> RunnerDisplayState:
    merge_status = model.merge_status
    secondary = _secondary_stale_label(model)

    if merge_status == "error":
        return RunnerDisplayState("merge_error", "머지 오류", "error", secondary)
    if merge_status == "conflict":
        return RunnerDisplayState("merge_conflict", "충돌", "error", secondary)
    if merge_status == "test_failed":
        return RunnerDisplayState("merge_test_failed", "테스트 실패", "error", secondary)
    if merge_status == "approval_required":
        return RunnerDisplayState("approval_required", "승인 필요", "approval", None, True)
    if (model.remaining_post_merge_tasks > 0 or model.merge_evidence_missing) and model.exit_reason == "completed":
        return RunnerDisplayState("post_merge_pending", "후처리 필요", "warn", secondary)
    if merge_status == "merged":
        return RunnerDisplayState("merged", "머지됨", "success", secondary)
    if merge_status in {"merge_pending", "queued"}:
        return RunnerDisplayState("merge_pending", "머지 대기", "info", secondary)
    if merge_status in {"merging", "testing"}:
        return RunnerDisplayState("merging", "머지 중", "info", secondary)
    if model.running:
        return RunnerDisplayState("running", "실행중", "info", secondary)
    if model.exit_reason == "completed":
        return RunnerDisplayState("completed", "완료", "success", secondary)
    if model.worktree_exists == "unknown" and not model.running:
        return RunnerDisplayState("history", "과거 기록", "muted", "과거 기록")
    return RunnerDisplayState("stopped", "중지됨", "muted", secondary)
