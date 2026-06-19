"""
BigQuery export mapper functions.

Each mapper converts a SQLAlchemy model row to a 7-column dict that matches
the personal_hub_events BigQuery schema.  Forbidden fields are never included
in the output even if they are present on the source model.

Allowed output columns: event_time, event_type, module, status,
                        duration_ms, severity, error_type
"""

from __future__ import annotations

_ALLOWED_KEYS = frozenset(
    {"event_time", "event_type", "module", "status", "duration_ms", "severity", "error_type"}
)


def _clean(row_dict: dict) -> dict:
    """Drop any key not in the 7-column allowlist (safety net)."""
    return {k: v for k, v in row_dict.items() if k in _ALLOWED_KEYS}


def map_monitoring_event(row) -> dict:
    """Convert a MonitoringEvent ORM row to a 7-column BigQuery dict.

    Fields used:
        timestamp       → event_time
        event_type      → event_type  (check / slot_detected / slot_booked / error)
        status          → status
        response_time_ms → duration_ms
    Fixed values:
        module = "naver_booking"  (MonitoringEvent has no module column)
        severity = None
        error_type = None
    """
    return _clean({
        "event_time": row.timestamp,
        "event_type": row.event_type,
        "module": "naver_booking",
        "status": row.status,
        "duration_ms": int(row.response_time_ms) if row.response_time_ms is not None else None,
        "severity": None,
        "error_type": None,
    })


def map_scheduled_task_log(row) -> dict:
    """Convert a ScheduledTaskLog ORM row to a 7-column BigQuery dict.

    Per plan §1 note: task_name → module pass-through is the design intent
    (bigquery-schema-design.md §3).  However module allowlist only contains
    "scheduled_task".  We use module="scheduled_task" fixed to guarantee
    allowlist compliance.

    Fields used:
        started_at          → event_time
        status              → status
        duration_seconds×1000 → duration_ms
    Fixed values:
        event_type = "task_run"
        module     = "scheduled_task"
        severity   = None
        error_type = None
    """
    duration_ms = (
        int(row.duration_seconds * 1000) if row.duration_seconds is not None else None
    )
    return _clean({
        "event_time": row.started_at,
        "event_type": "task_run",
        "module": "scheduled_task",
        "status": row.status,
        "duration_ms": duration_ms,
        "severity": None,
        "error_type": None,
    })


def map_test_run(row) -> dict:
    """Convert a TestRun ORM row to a 7-column BigQuery dict.

    Fields used:
        started_at          → event_time
        status              → status
        duration_seconds×1000 → duration_ms
    Fixed values:
        event_type = "test_run"
        module     = "test_run"
        severity   = None
        error_type = None
    """
    duration_ms = (
        int(row.duration_seconds * 1000) if row.duration_seconds is not None else None
    )
    return _clean({
        "event_time": row.started_at,
        "event_type": "test_run",
        "module": "test_run",
        "status": row.status,
        "duration_ms": duration_ms,
        "severity": None,
        "error_type": None,
    })


def map_error_log(row) -> dict:
    """Convert an ErrorLog ORM row to a 7-column BigQuery dict.

    error_log has no 'status' column; we derive status from severity.

    Fields used:
        created_at  → event_time
        severity    → severity  (critical / error / warning)
        severity    → status    (derived — no dedicated status column)
        error_type  → error_type
    Fixed values:
        event_type = "error"
        module     = "error_log"
        duration_ms = None
    """
    return _clean({
        "event_time": row.created_at,
        "event_type": "error",
        "module": "error_log",
        "status": row.severity,
        "duration_ms": None,
        "severity": row.severity,
        "error_type": row.error_type,
    })


def map_instagram_worker_status(row) -> dict:
    """Convert an InstagramWorkerStatus ORM row to a 7-column BigQuery dict.

    Fields used:
        last_heartbeat → event_time
        current_state  → status  (idle / crawling / processing)
    Fixed values:
        event_type  = "worker_state"
        module      = "instagram_worker"
        duration_ms = None
        severity    = None
        error_type  = None
    """
    return _clean({
        "event_time": row.last_heartbeat,
        "event_type": "worker_state",
        "module": "instagram_worker",
        "status": row.current_state,
        "duration_ms": None,
        "severity": None,
        "error_type": None,
    })
