from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_system_queue_invalid_next_run_time_keeps_remaining_seconds_null():
    from app.routes.system import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    row = {
        "id": 1,
        "date": "2026-04-24",
        "run_status": "queued",
        "error_count": 0,
        "last_error": None,
        "last_check_time": None,
        "next_run_time": "not-a-date",
        "interval": 60,
        "custom_interval": None,
        "biz_item_name": "테스트 예약",
        "naver_biz_item_id": "6309731",
        "business_name": "테스트 업체",
        "naver_business_id": "1630978",
        "business_type_id": 13,
    }
    mock_db = MagicMock()
    mock_db.execute.return_value.mappings.return_value.all.return_value = [row]

    with patch("app.routes.system.SessionLocal", return_value=mock_db):
        response = client.get("/api/v1/system/queue")

    assert response.status_code == 200
    assert response.json()[0]["remaining_seconds"] is None


def test_notification_format_time_info_bad_input_uses_original_order():
    from app.shared.notification.notification_service import NotificationService

    svc = object.__new__(NotificationService)

    assert svc._format_time_info(["bad-time", "오전 10:00"]) == "bad-time, 오전 10:00"


def test_notification_format_stock_info_keeps_existing_sort_contract():
    from app.shared.notification.notification_service import NotificationService

    svc = object.__new__(NotificationService)

    stocks = ["오후 1:00: 2매", "오전 10:00: 3매"]
    assert svc._format_stock_info(stocks) == "오전 10:00: <b>3매</b>\n오후 1:00: 2매"
