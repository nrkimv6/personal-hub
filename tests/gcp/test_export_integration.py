"""
Integration tests for export CLI (Phase T3 — dry-run, no real BigQuery).

These tests use real mapper/validator/argparse logic with mocked
DB session and BigQuery SDK only.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_TS = datetime(2026, 6, 1, 12, 0, 0)


def _make_session_empty():
    """Return a mock session that yields no rows for all 5 model queries."""
    call_count = [0]

    def query_side_effect(*args, **kwargs):
        call_count[0] += 1
        q = MagicMock()
        q.filter.return_value.all.return_value = []
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect
    return session


def _make_session_one_event():
    """Return a mock session with one valid MonitoringEvent row."""
    from types import SimpleNamespace
    rows = [
        [SimpleNamespace(timestamp=_TS, event_type="check", status="success", response_time_ms=50.0)],
        [],  # task logs
        [],  # test runs
        [],  # error logs
        [],  # worker statuses
    ]
    call_count = [0]

    def query_side_effect(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        q = MagicMock()
        result_set = rows[idx] if idx < len(rows) else []
        q.filter.return_value.all.return_value = result_set
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect
    return session


# ---------------------------------------------------------------------------
# T3 — Integration TC
# ---------------------------------------------------------------------------

def test_export_cli_dry_run_no_insert():
    """T3: export_events with dry_run=True does not call BigQuery SDK insert_rows_json."""
    from app.modules.bigquery_export.export import export_events

    session = _make_session_one_event()

    with patch("app.modules.bigquery_export.client._is_export_enabled", return_value=False):
        # Patch the bigquery module to detect any stray calls
        mock_bq_client = MagicMock()
        with patch.dict("sys.modules", {"google.cloud.bigquery": mock_bq_client}):
            summary = export_events(session, datetime(2026, 6, 1), datetime(2026, 6, 7), dry_run=True)

    # BigQuery Client constructor should NOT have been called
    mock_bq_client.Client.assert_not_called()

    assert summary.total_read == 1
    assert summary.total_inserted == 1  # dry-run counts as inserted


def test_export_cli_cost_guard_disabled():
    """T3: ENABLE_BIGQUERY_EXPORT=false with dry_run=False → CostGuardBlocked."""
    from app.modules.bigquery_export.client import CostGuardBlocked
    from app.modules.bigquery_export.export import export_events

    session = _make_session_one_event()

    with patch.dict(os.environ, {"ENABLE_BIGQUERY_EXPORT": "false"}):
        # With dry_run=False and gate disabled, we expect CostGuardBlocked
        # export_events calls insert_rows(dry_run=False) after validation
        with pytest.raises(CostGuardBlocked):
            export_events(session, datetime(2026, 6, 1), datetime(2026, 6, 7), dry_run=False)


def test_export_events_dry_run_empty_db():
    """T3: empty DB → ExportSummary all zeros, no errors."""
    from app.modules.bigquery_export.export import export_events

    session = _make_session_empty()
    summary = export_events(session, datetime(2026, 6, 1), datetime(2026, 6, 7), dry_run=True)

    assert summary.total_read == 0
    assert summary.total_valid == 0
    assert summary.total_inserted == 0
    assert summary.total_skipped == 0
    assert summary.errors == []


def test_export_cli_argparse_dry_run_default(capsys):
    """T3: CLI argparse — --apply absent → dry_run=True propagated."""
    import importlib.util
    import types

    # Dynamically import export_events.py script
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts", "gcp", "export_events.py",
    )
    spec = importlib.util.spec_from_file_location("export_events_cli", script_path)
    cli_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_module)

    args = cli_module.parse_args(["--since", "2026-06-01", "--until", "2026-06-07"])
    assert args.apply is False, "--apply should default to False (dry-run)"


def test_export_cli_argparse_apply_sets_live(capsys):
    """T3: CLI argparse — --apply present → apply=True."""
    import importlib.util

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts", "gcp", "export_events.py",
    )
    spec = importlib.util.spec_from_file_location("export_events_cli2", script_path)
    cli_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_module)

    args = cli_module.parse_args(["--since", "2026-06-01", "--until", "2026-06-07", "--apply"])
    assert args.apply is True
