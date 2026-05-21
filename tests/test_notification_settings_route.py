"""
notification.py get_notification_settings_from_db() 이름 기반 접근 TC
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "1")

from app.routes.notification import (
    _DEFAULT_NOTIFY_STATES,
    _normalize_notify_states,
    get_notification_settings_from_db,
    update_notification_settings_in_db,
)
from app.schemas.notification import NotificationSettingsUpdate


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

    def test_update_notification_settings_right_accepts_failure_warning_state(self):
        """R: 운영 실패 warning opt-in state가 저장/응답에서 유지된다."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (1,)
        settings = NotificationSettingsUpdate(
            enable_telegram=True,
            enable_desktop=False,
            notify_states=["available", "failure_warning"],
        )
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            result = update_notification_settings_in_db(settings)

        assert result.notify_states == ["available", "failure_warning"]
        assert mock_db.commit.called

    def test_update_notification_settings_boundary_filters_unknown_failure_state(self):
        """B: 미지원 state는 저장 전에 제거된다."""
        normalized = _normalize_notify_states(["failure_warning", "unknown_failure_state"])

        assert normalized == ["failure_warning"]

    def test_critical_force_send_reference_independent_from_notify_states(self):
        """Re: critical force-send는 notify_states opt-in 목록에 들어가지 않는다."""
        assert "failure_warning" not in _DEFAULT_NOTIFY_STATES
        assert _normalize_notify_states(["failure_warning"]) == ["failure_warning"]
        assert "critical" not in _DEFAULT_NOTIFY_STATES
        assert "failure_critical" not in _DEFAULT_NOTIFY_STATES
