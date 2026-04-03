"""dev-runner completed sentinel parsing helpers."""

from __future__ import annotations

from typing import Optional

LOG_COMPLETED_SENTINEL = "__COMPLETED__"
MERGE_LOG_COMPLETED_SENTINEL = "__MERGE_COMPLETED__"
LOG_COMPLETED_REASON_PREFIX = "__COMPLETED::"
MERGE_COMPLETED_REASON_PREFIX = "__MERGE_COMPLETED::"

FAILED_COMPLETION_REASONS = {
    "failed",
    "error",
    "rate_limit",
    "commit_failed",
    "quota_exhausted",
    "plan_result_missing",
    "auto_plan_failed",
    "verify_result_missing",
    "auto_verify_failed",
    "no_progress",
    "merge_failed",
}


def is_log_completed_payload(data: str) -> bool:
    return data.startswith(LOG_COMPLETED_SENTINEL) or data.startswith(
        LOG_COMPLETED_REASON_PREFIX
    )


def is_merge_completed_payload(data: str) -> bool:
    return data.startswith(MERGE_LOG_COMPLETED_SENTINEL) or data.startswith(
        MERGE_COMPLETED_REASON_PREFIX
    )


def normalize_completion_reason(reason: Optional[str]) -> str:
    normalized = str(reason or "completed").strip().lower()
    if normalized == "rate_limited":
        return "rate_limit"
    return normalized or "completed"


def is_failed_completion_reason(reason: Optional[str]) -> bool:
    return normalize_completion_reason(reason) in FAILED_COMPLETION_REASONS


def parse_log_completed_payload(data: str) -> tuple[str, str]:
    """`__COMPLETED__` sentinel을 (status, reason)으로 변환."""
    if data.startswith(LOG_COMPLETED_REASON_PREFIX):
        reason = normalize_completion_reason(
            data[len(LOG_COMPLETED_REASON_PREFIX):].rstrip("_")
        )
        status = "failed" if is_failed_completion_reason(reason) else "success"
        return status, reason
    suffix = data[len(LOG_COMPLETED_SENTINEL):]
    if suffix == ":FAILED":
        return "failed", "failed"
    return "success", "completed"


def parse_merge_completed_payload(data: str) -> tuple[str, str]:
    """`__MERGE_COMPLETED__` sentinel을 (status, reason)으로 변환."""
    if data.startswith(MERGE_COMPLETED_REASON_PREFIX):
        reason = normalize_completion_reason(
            data[len(MERGE_COMPLETED_REASON_PREFIX):].rstrip("_")
        )
        status = "failed" if is_failed_completion_reason(reason) else "success"
        return status, reason
    suffix = data[len(MERGE_LOG_COMPLETED_SENTINEL):]
    if suffix == ":FAILED":
        return "failed", "merge_failed"
    return "success", "completed"
