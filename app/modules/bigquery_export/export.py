"""
BigQuery batch export entrypoint.

Queries 5 source models in a given time range, maps each row to the
7-column BigQuery schema, validates, and inserts (or dry-runs).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

from app.modules.bigquery_export.mapper import (
    map_error_log,
    map_instagram_worker_status,
    map_monitoring_event,
    map_scheduled_task_log,
    map_test_run,
)
from app.modules.bigquery_export.client import insert_rows, InsertResult
from app.modules.bigquery_export.validator import validate_export_row

logger = logging.getLogger(__name__)

MAX_EXPORT_DAYS = 31
DEFAULT_TABLE_ID = "personal_hub.dataset.personal_hub_events"


@dataclass
class ExportSummary:
    total_read: int = 0
    total_valid: int = 0
    total_inserted: int = 0
    total_skipped: int = 0
    errors: List[str] = field(default_factory=list)


def export_events(
    db_session,
    since: datetime,
    until: datetime,
    dry_run: bool = True,
    table_id: str = DEFAULT_TABLE_ID,
) -> ExportSummary:
    """Export events from all 5 source models to BigQuery.

    Args:
        db_session: SQLAlchemy session.
        since:      Start of export window (inclusive).
        until:      End of export window (inclusive).
        dry_run:    When True, validate rows but skip actual SDK call.
        table_id:   Fully-qualified BigQuery table ID.

    Returns:
        ExportSummary with read/valid/inserted/skipped counts.

    Raises:
        ValueError: When until - since > 31 days.
    """
    if (until - since) > timedelta(days=MAX_EXPORT_DAYS):
        raise ValueError(
            f"export 범위가 {MAX_EXPORT_DAYS}일을 초과합니다 — "
            f"since={since.isoformat()}, until={until.isoformat()}"
        )

    summary = ExportSummary()

    # Lazy import models to avoid circular deps
    from app.models.monitoring_event import MonitoringEvent
    from app.models.scheduled_task_log import ScheduledTaskLog
    from app.models.test_run import TestRun
    from app.models.error_log import ErrorLog
    from app.models.instagram_worker_status import InstagramWorkerStatus

    sources = [
        (
            db_session.query(
                MonitoringEvent.timestamp,
                MonitoringEvent.event_type,
                MonitoringEvent.status,
                MonitoringEvent.response_time_ms,
            ).filter(
                MonitoringEvent.timestamp >= since,
                MonitoringEvent.timestamp <= until,
            ).all(),
            map_monitoring_event,
        ),
        (
            db_session.query(
                ScheduledTaskLog.started_at,
                ScheduledTaskLog.status,
                ScheduledTaskLog.duration_seconds,
                ScheduledTaskLog.task_name,
            ).filter(
                ScheduledTaskLog.started_at >= since,
                ScheduledTaskLog.started_at <= until,
            ).all(),
            map_scheduled_task_log,
        ),
        (
            db_session.query(
                TestRun.started_at,
                TestRun.status,
                TestRun.duration_seconds,
            ).filter(
                TestRun.started_at >= since,
                TestRun.started_at <= until,
            ).all(),
            map_test_run,
        ),
        (
            db_session.query(
                ErrorLog.created_at,
                ErrorLog.severity,
                ErrorLog.error_type,
            ).filter(
                ErrorLog.created_at >= since,
                ErrorLog.created_at <= until,
            ).all(),
            map_error_log,
        ),
        (
            db_session.query(
                InstagramWorkerStatus.last_heartbeat,
                InstagramWorkerStatus.current_state,
            ).filter(
                InstagramWorkerStatus.last_heartbeat >= since,
                InstagramWorkerStatus.last_heartbeat <= until,
            ).all(),
            map_instagram_worker_status,
        ),
    ]

    all_valid_rows: list[dict] = []

    for rows, mapper_fn in sources:
        for row in rows:
            summary.total_read += 1
            try:
                mapped = mapper_fn(row)
                validated = validate_export_row(mapped)
                all_valid_rows.append(validated)
                summary.total_valid += 1
            except ValueError as exc:
                msg = f"row 검증 실패 — {exc}"
                logger.warning(msg)
                summary.total_skipped += 1
                summary.errors.append(msg)

    # Insert in chunks of MAX_ROWS_PER_INSERT
    from app.modules.bigquery_export.client import MAX_ROWS_PER_INSERT

    for chunk_start in range(0, max(len(all_valid_rows), 1), MAX_ROWS_PER_INSERT):
        chunk = all_valid_rows[chunk_start: chunk_start + MAX_ROWS_PER_INSERT]
        if not chunk:
            break
        result: InsertResult = insert_rows(chunk, table_id, dry_run=dry_run)
        summary.total_inserted += result.rows_inserted
        summary.total_skipped += result.rows_skipped
        summary.errors.extend(result.errors)

    return summary
