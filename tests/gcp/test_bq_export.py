"""
Export function tests (Phase T1 — RIGHT-BICEP).

All tests use mocked DB session and dry_run=True — no real BigQuery calls.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.modules.bigquery_export.export import ExportSummary, export_events

_TS = datetime(2026, 6, 1, 12, 0, 0)
_SINCE = datetime(2026, 6, 1, 0, 0, 0)
_UNTIL = datetime(2026, 6, 7, 23, 59, 59)


def _make_session(
    monitoring_events=None,
    task_logs=None,
    test_runs=None,
    error_logs=None,
    worker_statuses=None,
):
    """Build a mock DB session that returns given rows per model."""
    if monitoring_events is None:
        monitoring_events = []
    if task_logs is None:
        task_logs = []
    if test_runs is None:
        test_runs = []
    if error_logs is None:
        error_logs = []
    if worker_statuses is None:
        worker_statuses = []

    all_result_sets = [
        monitoring_events,
        task_logs,
        test_runs,
        error_logs,
        worker_statuses,
    ]
    call_count = [0]

    def query_side_effect(*args, **kwargs):
        q = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        q.filter.return_value.all.return_value = all_result_sets[idx] if idx < len(all_result_sets) else []
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect
    return session


def _mon_row(**kw):
    defaults = dict(timestamp=_TS, event_type="check", status="success", response_time_ms=100.0)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _task_row(**kw):
    defaults = dict(started_at=_TS, status="success", duration_seconds=2, task_name="daily_job")
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _test_row(**kw):
    defaults = dict(started_at=_TS, status="completed", duration_seconds=5.0)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _err_row(**kw):
    defaults = dict(created_at=_TS, severity="error", error_type="ValueError")
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _worker_row(**kw):
    defaults = dict(last_heartbeat=_TS, current_state="idle")
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# R — Right pipeline
# ---------------------------------------------------------------------------

def test_export_events_R_pipeline():
    """R: 5 models → mapper → validator → dry-run insert → ExportSummary."""
    session = _make_session(
        monitoring_events=[_mon_row()],
        task_logs=[_task_row()],
        test_runs=[_test_row()],
        error_logs=[_err_row()],
        worker_statuses=[_worker_row()],
    )
    summary = export_events(session, _SINCE, _UNTIL, dry_run=True)
    assert isinstance(summary, ExportSummary)
    assert summary.total_read == 5
    assert summary.total_valid == 5
    assert summary.total_inserted == 5
    assert summary.total_skipped == 0
    assert summary.errors == []


# ---------------------------------------------------------------------------
# B — Boundary: range limit
# ---------------------------------------------------------------------------

def test_export_events_B_range_limit():
    """B: until - since > 31 days → ValueError."""
    session = _make_session()
    since = datetime(2026, 1, 1)
    until = datetime(2026, 3, 1)  # 59 days
    with pytest.raises(ValueError, match="31일"):
        export_events(session, since, until, dry_run=True)


def test_export_events_B_range_exactly_31_days():
    """B: exactly 31 days → passes."""
    session = _make_session()
    since = datetime(2026, 6, 1)
    until = since + timedelta(days=31)
    # Should not raise
    summary = export_events(session, since, until, dry_run=True)
    assert summary.total_read == 0


# ---------------------------------------------------------------------------
# I — Inverse: no SELECT *
# ---------------------------------------------------------------------------

def test_export_events_I_no_select_star():
    """I: DB queries use specific columns (not SELECT *).

    The export_events function issues .query(Col1, Col2, ...) calls.
    We verify that each query() call receives specific column arguments
    rather than the full model class alone.
    """
    captured_queries = []

    def query_side_effect(*args, **kwargs):
        captured_queries.append(args)
        q = MagicMock()
        q.filter.return_value.all.return_value = []
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    export_events(session, _SINCE, _UNTIL, dry_run=True)

    # All 5 query calls should pass multiple column args (not just the model)
    assert len(captured_queries) == 5, f"Expected 5 query calls, got {len(captured_queries)}"
    for args in captured_queries:
        # Each call should have >1 positional arg (individual columns, not SELECT *)
        assert len(args) > 1, (
            f"query() called with only 1 arg — possible SELECT * equivalent: {args}"
        )


# ---------------------------------------------------------------------------
# E — Error: invalid row skipped
# ---------------------------------------------------------------------------

def test_export_events_E_invalid_row_skipped():
    """E: invalid source row (maps to bad event_type) is skipped, total_skipped++."""
    bad_mon = SimpleNamespace(
        timestamp=_TS,
        event_type="INVALID_TYPE",  # not in allowlist
        status="success",
        response_time_ms=100.0,
    )
    session = _make_session(monitoring_events=[bad_mon])
    summary = export_events(session, _SINCE, _UNTIL, dry_run=True)
    assert summary.total_read == 1
    assert summary.total_valid == 0
    assert summary.total_skipped == 1
    assert len(summary.errors) >= 1
