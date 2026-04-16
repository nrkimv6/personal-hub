import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.services.operational_issue_store import (
    OperationalIssueReporter,
    OperationalIssueSource,
    OperationalIssueStore,
)


def _make_error(message: str) -> Exception:
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        return exc


def test_operational_issue_store_records_and_filters(tmp_path):
    log_path = tmp_path / "operational-issues.jsonl"

    with patch.object(OperationalIssueStore, "FILE_PATH", log_path):
        OperationalIssueStore.record(
            error=_make_error("database down"),
            source=OperationalIssueSource.DATABASE,
            severity="critical",
            context={"step": "connect"},
        )
        OperationalIssueStore.record(
            error=_make_error("migration failed"),
            source=OperationalIssueSource.MIGRATION,
            severity="error",
            context={"step": "upgrade"},
        )

        db_items = OperationalIssueStore.list(source=OperationalIssueSource.DATABASE, limit=10)
        search_items = OperationalIssueStore.list(search="upgrade", limit=10)

    assert len(db_items) == 1
    assert db_items[0]["source"] == OperationalIssueSource.DATABASE
    assert search_items[0]["source"] == OperationalIssueSource.MIGRATION


def test_operational_issue_reporter_dedups_telegram(tmp_path):
    log_path = tmp_path / "operational-issues.jsonl"

    OperationalIssueReporter._recent_alerts.clear()
    with patch.object(OperationalIssueStore, "FILE_PATH", log_path), \
         patch("app.services.error_collector.ErrorCollector.capture_sync") as mock_capture, \
         patch.object(OperationalIssueReporter, "_send_telegram") as mock_send:
        error = _make_error("connection refused")

        OperationalIssueReporter.report(
            error=error,
            source=OperationalIssueSource.DATABASE,
            severity="critical",
            context={"caller": "test"},
            notify=True,
            persist_error_log=True,
        )
        OperationalIssueReporter.report(
            error=error,
            source=OperationalIssueSource.DATABASE,
            severity="critical",
            context={"caller": "test"},
            notify=True,
            persist_error_log=True,
        )

    assert mock_capture.call_count == 2
    assert mock_send.call_count == 1

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first_record = json.loads(lines[0])
    assert first_record["source"] == OperationalIssueSource.DATABASE


def test_operational_issue_api_returns_file_backed_items(tmp_path):
    log_path = tmp_path / "operational-issues.jsonl"

    with patch.object(OperationalIssueStore, "FILE_PATH", log_path):
        OperationalIssueStore.record(
            error=_make_error("column missing"),
            source=OperationalIssueSource.MIGRATION,
            severity="critical",
            context={"phase": "startup"},
        )

        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/v1/errors/operational?source=migration&limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source"] == OperationalIssueSource.MIGRATION
