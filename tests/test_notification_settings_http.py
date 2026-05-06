"""
T5: GET /api/v1/notification/settings — HTTP 레벨 응답 계약 핀 TC

pytest.mark.http — /merge-test 단계에서 main 머지 후 실행.

목표:
  - /api/v1/notification/settings 응답이 enable_telegram, enable_desktop, notify_states 키를 포함하는지 핀
  - .mappings().first() + 이름 기반 접근 전환 이후 계약 유지 확인
"""
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")

from app.routes.notification import router, _DEFAULT_NOTIFY_STATES

pytestmark = pytest.mark.http


@pytest.fixture
def notif_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _make_notif_db(row):
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.first.return_value = row
    return mock_db


class TestNotificationSettingsHttpContract:

    def test_GET_notification_settings_right_returns_named_fields(self, notif_client):
        """R: DB 행 존재 시 enable_telegram/enable_desktop/notify_states 키 반환"""
        row = {
            "enable_telegram": True,
            "enable_desktop": False,
            "notify_states": json.dumps(["available", "booking_success"]),
        }
        with patch("app.routes.notification.SessionLocal", return_value=_make_notif_db(row)):
            resp = notif_client.get("/api/v1/notification/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enable_telegram"] is True
        assert data["enable_desktop"] is False
        assert "available" in data["notify_states"]
        assert "booking_success" in data["notify_states"]

    def test_GET_notification_settings_boundary_no_row_uses_defaults(self, notif_client):
        """B: DB 행 없으면 기본값으로 응답 (enable_telegram=True, notify_states=_DEFAULT)"""
        with patch("app.routes.notification.SessionLocal", return_value=_make_notif_db(None)):
            resp = notif_client.get("/api/v1/notification/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enable_telegram"] is True
        assert data["enable_desktop"] is True
        assert data["notify_states"] == _DEFAULT_NOTIFY_STATES

    def test_GET_notification_settings_error_db_down_returns_defaults(self, notif_client):
        """E: DB 예외 시도 기본값으로 응답 (서비스 중단 없음)"""
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB down")
        with patch("app.routes.notification.SessionLocal", return_value=mock_db):
            resp = notif_client.get("/api/v1/notification/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enable_telegram"] is True
        assert data["notify_states"] == _DEFAULT_NOTIFY_STATES

    def test_GET_notification_settings_reference_shuffled_keys_same_response(self, notif_client):
        """Re: key 순서가 뒤집혀도 이름 기반 접근이라 응답 동일"""
        row = {
            "notify_states": json.dumps(["available"]),
            "enable_desktop": True,
            "enable_telegram": False,
        }
        with patch("app.routes.notification.SessionLocal", return_value=_make_notif_db(row)):
            resp = notif_client.get("/api/v1/notification/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enable_telegram"] is False
        assert data["enable_desktop"] is True
        assert data["notify_states"] == ["available"]
