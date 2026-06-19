"""
Mapper tests (Phase T1 — RIGHT-BICEP).

Tests cover:
  R  — correct 7-column output, correct types
  I  — forbidden fields never appear in output
  B  — fixed field values enforced by mapper
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.modules.bigquery_export.mapper import (
    map_error_log,
    map_instagram_worker_status,
    map_monitoring_event,
    map_scheduled_task_log,
    map_test_run,
)

ALLOWED_KEYS = frozenset(
    {"event_time", "event_type", "module", "status", "duration_ms", "severity", "error_type"}
)

FORBIDDEN_FIELDS = [
    "message", "traceback", "context", "account_id", "url_token",
    "slots_info", "error_message", "details", "worker_id", "proxy_url",
    "target_url", "graphql_response",
]

_TS = datetime(2026, 6, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# MonitoringEvent
# ---------------------------------------------------------------------------

def _make_monitoring_event(**overrides):
    base = dict(
        timestamp=_TS,
        event_type="check",
        status="success",
        response_time_ms=250.0,
        # forbidden fields that MUST be dropped
        slots_info='{"foo":1}',
        error_message="some error",
        proxy_url="http://1.2.3.4:8080",
        graphql_response='{"data":{}}',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_monitoring_event_R_7cols():
    """R: output dict has exactly 7 allowed columns with correct types."""
    row = _make_monitoring_event()
    result = map_monitoring_event(row)
    assert set(result.keys()) == ALLOWED_KEYS
    assert result["event_time"] == _TS
    assert result["event_type"] == "check"
    assert result["module"] == "naver_booking"
    assert result["status"] == "success"
    assert result["duration_ms"] == 250  # converted to int
    assert result["severity"] is None
    assert result["error_type"] is None


def test_map_monitoring_event_I_no_forbidden_fields():
    """I: forbidden fields on source are dropped from output."""
    row = _make_monitoring_event()
    result = map_monitoring_event(row)
    for key in FORBIDDEN_FIELDS:
        assert key not in result, f"Forbidden field {key!r} found in mapper output"


def test_map_monitoring_event_R_module_fixed():
    """R: module is always 'naver_booking' (no module column on source)."""
    row = _make_monitoring_event()
    assert map_monitoring_event(row)["module"] == "naver_booking"


def test_map_monitoring_event_R_response_time_none():
    """R: duration_ms=None when response_time_ms is None."""
    row = _make_monitoring_event(response_time_ms=None)
    assert map_monitoring_event(row)["duration_ms"] is None


# ---------------------------------------------------------------------------
# ScheduledTaskLog
# ---------------------------------------------------------------------------

def _make_task_log(**overrides):
    base = dict(
        started_at=_TS,
        status="success",
        duration_seconds=5,
        task_name="some_task",
        error_message="err",
        details='{"k":"v"}',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_scheduled_task_log_R_7cols():
    """R: output dict has exactly 7 columns."""
    result = map_scheduled_task_log(_make_task_log())
    assert set(result.keys()) == ALLOWED_KEYS


def test_map_scheduled_task_log_R_fixed_event_type():
    """R: event_type is always 'task_run'."""
    result = map_scheduled_task_log(_make_task_log())
    assert result["event_type"] == "task_run"


def test_map_scheduled_task_log_R_module_fixed():
    """R: module is always 'scheduled_task' (allowlist compliance)."""
    result = map_scheduled_task_log(_make_task_log())
    assert result["module"] == "scheduled_task"


def test_map_scheduled_task_log_R_duration_conversion():
    """R: duration_seconds × 1000 → duration_ms."""
    result = map_scheduled_task_log(_make_task_log(duration_seconds=3))
    assert result["duration_ms"] == 3000


def test_map_scheduled_task_log_I_no_forbidden_fields():
    """I: forbidden fields dropped from output."""
    result = map_scheduled_task_log(_make_task_log())
    for key in FORBIDDEN_FIELDS:
        assert key not in result


# ---------------------------------------------------------------------------
# TestRun
# ---------------------------------------------------------------------------

def _make_test_run(**overrides):
    base = dict(
        started_at=_TS,
        status="completed",
        duration_seconds=12.5,
        log_file_path="/tmp/log.txt",
        xml_file_path="/tmp/result.xml",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_test_run_R_7cols():
    """R: output dict has exactly 7 columns."""
    result = map_test_run(_make_test_run())
    assert set(result.keys()) == ALLOWED_KEYS


def test_map_test_run_R_fixed_fields():
    """R: event_type='test_run', module='test_run'."""
    result = map_test_run(_make_test_run())
    assert result["event_type"] == "test_run"
    assert result["module"] == "test_run"


def test_map_test_run_I_no_forbidden_fields():
    """I: no forbidden fields in output."""
    result = map_test_run(_make_test_run())
    for key in FORBIDDEN_FIELDS:
        assert key not in result


# ---------------------------------------------------------------------------
# ErrorLog
# ---------------------------------------------------------------------------

def _make_error_log(**overrides):
    base = dict(
        created_at=_TS,
        severity="critical",
        error_type="ValueError",
        message="some error message",
        traceback="Traceback...",
        context={"account_id": "user1"},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_error_log_B_fixed_fields():
    """B: event_type='error' fixed, module='error_log' fixed,
       status=row.severity, severity=row.severity (critical)."""
    row = _make_error_log(severity="critical")
    result = map_error_log(row)
    assert result["event_type"] == "error"
    assert result["module"] == "error_log"
    assert result["status"] == "critical"
    assert result["severity"] == "critical"


def test_map_error_log_R_7cols():
    """R: output has exactly 7 columns."""
    result = map_error_log(_make_error_log())
    assert set(result.keys()) == ALLOWED_KEYS


def test_map_error_log_I_no_forbidden_fields():
    """I: forbidden fields (message, traceback, context) dropped."""
    result = map_error_log(_make_error_log())
    for key in FORBIDDEN_FIELDS:
        assert key not in result


# ---------------------------------------------------------------------------
# InstagramWorkerStatus
# ---------------------------------------------------------------------------

def _make_worker_status(**overrides):
    base = dict(
        last_heartbeat=_TS,
        current_state="idle",
        worker_id="uuid-1234",
        current_account="account1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_instagram_worker_B_module_fixed():
    """B: module='instagram_worker' fixed regardless of source."""
    result = map_instagram_worker_status(_make_worker_status())
    assert result["module"] == "instagram_worker"


def test_map_instagram_worker_R_7cols():
    """R: output has exactly 7 columns."""
    result = map_instagram_worker_status(_make_worker_status())
    assert set(result.keys()) == ALLOWED_KEYS


def test_map_instagram_worker_R_event_type_fixed():
    """R: event_type='worker_state' fixed."""
    result = map_instagram_worker_status(_make_worker_status())
    assert result["event_type"] == "worker_state"


def test_map_instagram_worker_R_status_from_current_state():
    """R: status comes from current_state field."""
    result = map_instagram_worker_status(_make_worker_status(current_state="crawling"))
    assert result["status"] == "crawling"


def test_map_instagram_worker_I_no_forbidden_fields():
    """I: worker_id and current_account (forbidden) are not in output."""
    result = map_instagram_worker_status(_make_worker_status())
    for key in FORBIDDEN_FIELDS:
        assert key not in result
