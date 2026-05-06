"""Merge state model for dev-runner listener side.

The listener owns the Redis merge lifecycle keys. See
``docs/dev-guide/merge-state-contract.md`` for the runtime boundary with the
wtools post-merge subprocess.
"""

from __future__ import annotations

from enum import Enum


QUEUED = "queued"
MERGING = "merging"
MERGED = "merged"
ERROR = "error"
APPROVAL_REQUIRED = "approval_required"
CONFLICT = "conflict"
TEST_FAILED = "test_failed"
PRECHECK_FAILED = "precheck_failed"
NEEDS_RESOLVE_CONTINUATION = "needs_resolve_continuation"
RESIDUE_BLOCKED = "residue_blocked"
RESOLVING = "resolving"
TESTING = "testing"
FIXING = "fixing"
PENDING_MERGE = "pending_merge"
PRE_MERGE = "pre_merge"


TERMINAL_STATUSES = frozenset(
    {
        MERGED,
        ERROR,
        APPROVAL_REQUIRED,
        CONFLICT,
        TEST_FAILED,
        PRECHECK_FAILED,
        NEEDS_RESOLVE_CONTINUATION,
        RESIDUE_BLOCKED,
    }
)
"""Statuses that represent an executor outcome or a user-action wait state."""

ACTIVE_STATUSES = frozenset(
    {PRE_MERGE, QUEUED, MERGING, PENDING_MERGE, RESOLVING, TESTING, FIXING}
)
"""Statuses that indicate merge work is actively queued or being processed."""

APPROVAL_STATUSES = frozenset({APPROVAL_REQUIRED})
"""Statuses requiring an explicit user approval action before retry."""

RETRYABLE_STATUSES = frozenset(
    {APPROVAL_REQUIRED, CONFLICT, TEST_FAILED, PRECHECK_FAILED, NEEDS_RESOLVE_CONTINUATION, ERROR}
)
"""Terminal statuses that a user-commanded retry may intentionally replace."""


class RetryAction(str, Enum):
    INLINE_MERGE = "inline-merge"
    RETRY_MERGE = "retry-merge"
    DIRECT_MERGE = "direct-merge"
    APPROVED_RETRY = "approved-retry"


class MergeCleanupAction(str, Enum):
    SKIP = "skip"
    INLINE_MERGE = "inline-merge"
    FALLBACK_DONE = "fallback-done"
    BLOCKED_TERMINAL = "blocked-terminal"


OVERRIDE_MATRIX = {
    RetryAction.INLINE_MERGE: frozenset(),
    RetryAction.RETRY_MERGE: frozenset(),
    # Current listener call-sites normalize direct-merge to APPROVED_RETRY.
    # Keep the enum no wider than approved retry for any direct callers.
    RetryAction.DIRECT_MERGE: RETRYABLE_STATUSES,
    RetryAction.APPROVED_RETRY: RETRYABLE_STATUSES,
}


def normalize_status(status: object) -> str:
    if status is None:
        return ""
    if isinstance(status, bytes):
        return status.decode("utf-8", errors="replace").strip().lower()
    return str(status).strip().lower()


def normalize_action(action: object) -> RetryAction:
    if isinstance(action, RetryAction):
        return action
    value = normalize_status(action)
    if value in {"approved_retry", "approve-service-lock", "approve_service_lock"}:
        return RetryAction.APPROVED_RETRY
    try:
        return RetryAction(value)
    except ValueError:
        return RetryAction.INLINE_MERGE


def is_transition_allowed(from_status: object, to_status: object, action: object = None) -> bool:
    current = normalize_status(from_status)
    target = normalize_status(to_status)
    if not target:
        return False
    if not current or current == target:
        return True

    retry_action = normalize_action(action)
    if current in TERMINAL_STATUSES:
        return current in OVERRIDE_MATRIX.get(retry_action, frozenset())
    return True


def should_enter_inline_merge(
    merge_status: object,
    merge_requested: object,
    exit_code: int | None,
    stop_stage: object = None,
) -> bool:
    status = normalize_status(merge_status)
    if status in TERMINAL_STATUSES:
        return False
    if normalize_status(stop_stage) == "pre_review":
        return False
    if not merge_requested:
        return False
    return exit_code == 0 or exit_code is not None
