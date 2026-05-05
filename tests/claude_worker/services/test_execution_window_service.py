from datetime import datetime

import pytest

from app.modules.claude_worker.services.execution_window_service import (
    LLMExecutionWindowService,
    max_resume_at,
)


def test_default_config_allows_execution(tmp_path):
    svc = LLMExecutionWindowService(tmp_path / "missing.json")

    decision = svc.decide(datetime(2026, 5, 5, 10, 0))

    assert decision.allowed is True


def test_allowed_window_blocks_outside_and_reports_next_start(tmp_path):
    path = tmp_path / "windows.json"
    svc = LLMExecutionWindowService(path)
    svc.save_config(
        {
            "timezone": "Asia/Seoul",
            "allowed_windows": [{"start": "19:00", "end": "22:00"}],
            "quiet_windows": [],
        }
    )

    decision = svc.decide(datetime(2026, 5, 5, 10, 0))

    assert decision.allowed is False
    assert decision.reason == "paused_by_window"
    assert decision.next_allowed_at == datetime(2026, 5, 5, 19, 0)


def test_midnight_crossing_allowed_window(tmp_path):
    path = tmp_path / "windows.json"
    svc = LLMExecutionWindowService(path)
    svc.save_config(
        {
            "timezone": "Asia/Seoul",
            "allowed_windows": [{"start": "23:00", "end": "02:00"}],
            "quiet_windows": [],
        }
    )

    assert svc.decide(datetime(2026, 5, 6, 1, 0)).allowed is True
    assert svc.decide(datetime(2026, 5, 6, 3, 0)).allowed is False


def test_quiet_window_overrides_allowed_window(tmp_path):
    path = tmp_path / "windows.json"
    svc = LLMExecutionWindowService(path)
    svc.save_config(
        {
            "timezone": "Asia/Seoul",
            "allowed_windows": [{"start": "09:00", "end": "18:00"}],
            "quiet_windows": [{"start": "12:00", "end": "13:00"}],
        }
    )

    decision = svc.decide(datetime(2026, 5, 5, 12, 30))

    assert decision.allowed is False
    assert decision.next_allowed_at == datetime(2026, 5, 5, 13, 0)


def test_invalid_window_payload_rejected(tmp_path):
    svc = LLMExecutionWindowService(tmp_path / "windows.json")

    with pytest.raises(ValueError):
        svc.save_config(
            {
                "timezone": "Asia/Seoul",
                "allowed_windows": [{"start": "25:00", "end": "26:00"}],
                "quiet_windows": [],
            }
        )


def test_invalid_timezone_rejected(tmp_path):
    svc = LLMExecutionWindowService(tmp_path / "windows.json")

    with pytest.raises(ValueError):
        svc.save_config(
            {
                "timezone": "No/SuchZone",
                "allowed_windows": [],
                "quiet_windows": [],
            }
        )


def test_overlapping_windows_rejected(tmp_path):
    svc = LLMExecutionWindowService(tmp_path / "windows.json")

    with pytest.raises(ValueError):
        svc.save_config(
            {
                "timezone": "Asia/Seoul",
                "allowed_windows": [
                    {"start": "09:00", "end": "12:00"},
                    {"start": "11:00", "end": "13:00"},
                ],
                "quiet_windows": [],
            }
        )


def test_max_resume_at_uses_later_quota_or_window_time():
    assert max_resume_at(datetime(2026, 5, 5, 19, 0), datetime(2026, 5, 5, 20, 0)) == datetime(
        2026, 5, 5, 20, 0
    )
