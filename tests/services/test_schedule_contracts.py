"""Schedule value health contract tests."""

import json
from datetime import date

import pytest

from app.services.schedule_contracts import (
    build_time_window_candidate_summary,
    validate_no_exact_time_windows,
)


def test_candidate_summary_R_counts_range_window_candidates():
    summary = build_time_window_candidate_summary(
        {
            "daily_runs": 2,
            "time_windows": [{"start": "09:00", "end": "12:00"}],
        },
        start_date=date(2026, 5, 21),
    )

    assert summary["health"] == "ok"
    assert summary["reason"] is None
    assert summary["candidate_count"] == 2
    assert summary["daily_runs"] == 2
    assert summary["time_window_count"] == 1
    assert summary["has_exact_time_window"] is False


def test_candidate_summary_B_exact_only_window_reports_zero_candidate_error():
    summary = build_time_window_candidate_summary(
        json.dumps(
            {
                "daily_runs": 2,
                "time_windows": [
                    {"start": "07:00", "end": "07:00"},
                    {"start": "09:20", "end": "09:20"},
                ],
            }
        ),
        start_date=date(2026, 5, 21),
    )

    assert summary["health"] == "error"
    assert summary["reason"] == "exact_time_window_zero_candidates"
    assert summary["candidate_count"] == 0
    assert summary["daily_runs"] == 2
    assert summary["time_window_count"] == 2
    assert summary["has_exact_time_window"] is True


def test_candidate_summary_E_invalid_json_reports_error_reason():
    summary = build_time_window_candidate_summary("{")

    assert summary["health"] == "error"
    assert summary["reason"] == "invalid_schedule_value_json"
    assert summary["candidate_count"] == 0


def test_validate_no_exact_time_windows_E_rejects_exact_window():
    with pytest.raises(ValueError, match="start"):
        validate_no_exact_time_windows(
            {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "09:00"}],
            }
        )
