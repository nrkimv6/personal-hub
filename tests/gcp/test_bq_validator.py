"""
Validator tests (Phase T1 — RIGHT-BICEP).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.bigquery_export.validator import (
    ALLOWED_EVENT_TYPES,
    validate_export_row,
)

_TS = datetime(2026, 6, 1, 12, 0, 0)


def _valid_row(**overrides) -> dict:
    base = {
        "event_time": _TS,
        "event_type": "check",
        "module": "naver_booking",
        "status": "success",
        "duration_ms": None,
        "severity": None,
        "error_type": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# R — Right result
# ---------------------------------------------------------------------------

def test_validate_R_valid_row():
    """R: a clean 7-column row passes and is returned unchanged."""
    row = _valid_row()
    result = validate_export_row(row)
    assert result == row


def test_validate_R_returns_dict_with_only_allowed_keys():
    """R: returned dict contains only the 7 allowlist keys."""
    from app.modules.bigquery_export.validator import BIGQUERY_EXPORT_ALLOWLIST
    result = validate_export_row(_valid_row())
    assert set(result.keys()) <= BIGQUERY_EXPORT_ALLOWLIST


# ---------------------------------------------------------------------------
# E — Error
# ---------------------------------------------------------------------------

def test_validate_E_forbidden_field():
    """E: row with a forbidden field raises ValueError."""
    row = _valid_row()
    row["message"] = "some error message"
    with pytest.raises(ValueError, match="금지 필드"):
        validate_export_row(row)


def test_validate_E_missing_required_event_time():
    """E: missing event_time → ValueError."""
    row = _valid_row()
    del row["event_time"]
    with pytest.raises(ValueError, match="필수 필드"):
        validate_export_row(row)


def test_validate_E_missing_required_event_type():
    """E: missing event_type → ValueError."""
    row = _valid_row()
    del row["event_type"]
    with pytest.raises(ValueError, match="필수 필드"):
        validate_export_row(row)


def test_validate_E_missing_required_module():
    """E: missing module → ValueError."""
    row = _valid_row()
    del row["module"]
    with pytest.raises(ValueError, match="필수 필드"):
        validate_export_row(row)


def test_validate_E_missing_required_status():
    """E: missing status → ValueError."""
    row = _valid_row()
    del row["status"]
    with pytest.raises(ValueError, match="필수 필드"):
        validate_export_row(row)


def test_validate_E_none_required_field():
    """E: required field set to None → ValueError."""
    row = _valid_row(status=None)
    with pytest.raises(ValueError, match="None"):
        validate_export_row(row)


# ---------------------------------------------------------------------------
# B — Boundary: event_type
# ---------------------------------------------------------------------------

def test_validate_B_event_type_boundary_all_valid():
    """B: all 7 allowed event_type values pass validation."""
    for et in ALLOWED_EVENT_TYPES:
        row = _valid_row(event_type=et)
        # should not raise
        validate_export_row(row)


def test_validate_B_event_type_boundary_invalid():
    """B: 8th value (not in allowlist) → ValueError."""
    row = _valid_row(event_type="unknown_event")
    with pytest.raises(ValueError, match="event_type"):
        validate_export_row(row)


# ---------------------------------------------------------------------------
# B — Boundary: duration_ms
# ---------------------------------------------------------------------------

def test_validate_B_duration_ms_negative():
    """B: duration_ms < 0 → ValueError."""
    row = _valid_row(duration_ms=-1)
    with pytest.raises(ValueError, match="duration_ms"):
        validate_export_row(row)


def test_validate_B_duration_ms_none():
    """B: duration_ms = None → passes."""
    row = _valid_row(duration_ms=None)
    validate_export_row(row)  # should not raise


def test_validate_B_duration_ms_zero():
    """B: duration_ms = 0 → passes (boundary: minimum valid value)."""
    row = _valid_row(duration_ms=0)
    validate_export_row(row)


# ---------------------------------------------------------------------------
# B — Boundary: severity
# ---------------------------------------------------------------------------

def test_validate_B_severity_valid_values():
    """B: all allowed severity values pass."""
    for sev in ("critical", "error", "warning"):
        row = _valid_row(severity=sev)
        validate_export_row(row)


def test_validate_B_severity_none():
    """B: severity=None → passes."""
    row = _valid_row(severity=None)
    validate_export_row(row)


def test_validate_B_severity_invalid():
    """B: unknown severity → ValueError."""
    row = _valid_row(severity="HIGH")
    with pytest.raises(ValueError, match="severity"):
        validate_export_row(row)


# ---------------------------------------------------------------------------
# B — Boundary: module
# ---------------------------------------------------------------------------

def test_validate_B_module_invalid():
    """B: unknown module → ValueError."""
    row = _valid_row(module="unknown_module")
    with pytest.raises(ValueError, match="module"):
        validate_export_row(row)
