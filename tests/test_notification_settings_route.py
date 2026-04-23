"""
notification.py get_notification_settings_from_db() 이름 기반 접근 TC
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "1")

from app.routes.notification import get_notification_settings_from_db, _DEFAULT_NOTIFY_STATES


def _make_mock_db(first_result):
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = first_result
    return mock_db


class TestGetNotificationSettingsNamedAccess:

    def test_get_notification_settings_right_named_fields(self):
        """R: 이름 기반 row에서 enable_telegram, enable_desktop, notify_states가 올바르게 반환"""
        mock_db = _make_mock_db({
            "enable_telegram": True,
            "enable_desktop": False,
            "notify_states": '["available", "booking_success"]',
        })
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            result = get_notification_settings_from_db()
        assert result.enable_telegram is True
        assert result.enable_desktop is False
        assert result.notify_states == ["available", "booking_success"]

    def test_get_notification_settings_boundary_missing_row_defaults(self):
        """B: row가 없으면 _DEFAULT_NOTIFY_STATES 기본값 반환"""
        mock_db = _make_mock_db(None)
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            result = get_notification_settings_from_db()
        assert result.enable_telegram is True
        assert result.enable_desktop is True
        assert result.notify_states == _DEFAULT_NOTIFY_STATES

    def test_get_notification_settings_error_db_exception_defaults(self):
        """E: db.execute 예외 시 기본값으로 폴백"""
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB down")
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            result = get_notification_settings_from_db()
        assert result.enable_telegram is True
        assert result.notify_states == _DEFAULT_NOTIFY_STATES

    def test_get_notification_settings_reference_shuffled_keys(self):
        """Re: key 순서를 섞은 mapping dict에서도 이름 기반 접근으로 올바른 값"""
        mock_db = _make_mock_db({
            "notify_states": '["available"]',
            "enable_desktop": True,
            "enable_telegram": False,  # 순서 반전
        })
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            result = get_notification_settings_from_db()
        assert result.enable_telegram is False
        assert result.enable_desktop is True
        assert result.notify_states == ["available"]
