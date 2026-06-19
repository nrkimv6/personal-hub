"""
BigQuery export row validator.

Implements the allowlist gate from bigquery-schema-design.md §6.
"""

from __future__ import annotations

# --- Allowlists (SSOT: bigquery-schema-design.md §2) ---

BIGQUERY_EXPORT_ALLOWLIST: frozenset[str] = frozenset(
    {"event_time", "event_type", "module", "status", "duration_ms", "severity", "error_type"}
)

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"event_time", "event_type", "module", "status"}
)

ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {"check", "slot_detected", "slot_booked", "task_run", "test_run", "error", "worker_state"}
)

ALLOWED_MODULES: frozenset[str] = frozenset(
    {"naver_booking", "scheduled_task", "test_run", "error_log", "instagram_worker"}
)

ALLOWED_SEVERITIES: frozenset[str] = frozenset(
    {"critical", "error", "warning"}
)


def validate_export_row(row: dict) -> dict:
    """Validate a BigQuery export row dict.

    Checks:
    1. No forbidden (non-allowlist) fields.
    2. Required fields are present and non-None.
    3. event_type is in ALLOWED_EVENT_TYPES.
    4. module is in ALLOWED_MODULES.
    5. severity is in ALLOWED_SEVERITIES or None.
    6. duration_ms is a non-negative integer or None.

    Returns the filtered dict (allowlist keys only) on success.
    Raises ValueError on any violation.
    """
    # 1. Forbidden field check
    extra_keys = set(row.keys()) - BIGQUERY_EXPORT_ALLOWLIST
    if extra_keys:
        raise ValueError(f"BigQuery export: 금지 필드 유입 차단 — {sorted(extra_keys)}")

    # 2. Required fields
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise ValueError(f"BigQuery export: 필수 필드 누락 — {sorted(missing)}")
    for field in REQUIRED_FIELDS:
        if row.get(field) is None:
            raise ValueError(f"BigQuery export: 필수 필드가 None — {field}")

    # 3. event_type allowlist
    event_type = row["event_type"]
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"BigQuery export: 허용되지 않은 event_type={event_type!r}. "
            f"허용값: {sorted(ALLOWED_EVENT_TYPES)}"
        )

    # 4. module allowlist
    module = row["module"]
    if module not in ALLOWED_MODULES:
        raise ValueError(
            f"BigQuery export: 허용되지 않은 module={module!r}. "
            f"허용값: {sorted(ALLOWED_MODULES)}"
        )

    # 5. severity allowlist (optional)
    severity = row.get("severity")
    if severity is not None and severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"BigQuery export: 허용되지 않은 severity={severity!r}. "
            f"허용값: {sorted(ALLOWED_SEVERITIES)}"
        )

    # 6. duration_ms range (optional)
    duration_ms = row.get("duration_ms")
    if duration_ms is not None:
        if not isinstance(duration_ms, int):
            raise ValueError(
                f"BigQuery export: duration_ms는 정수여야 합니다 — type={type(duration_ms).__name__}"
            )
        if duration_ms < 0:
            raise ValueError(
                f"BigQuery export: duration_ms는 0 이상이어야 합니다 — {duration_ms}"
            )

    # Return only allowlist keys (drop any extras that slipped past step 1)
    return {k: v for k, v in row.items() if k in BIGQUERY_EXPORT_ALLOWLIST}
