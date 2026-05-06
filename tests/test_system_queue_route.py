"""
system.py get_monitoring_queue() 이름 기반 접근 TC
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("TESTING", "1")

from fastapi.testclient import TestClient
from fastapi import FastAPI
from app.routes.system import router


@pytest.fixture
def queue_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _make_mapping_row(**kwargs):
    defaults = {
        "id": 1,
        "date": "2026-04-24",
        "run_status": "queued",
        "error_count": 0,
        "last_error": None,
        "last_check_time": None,
        "next_run_time": None,
        "interval": 60,
        "custom_interval": None,
        "biz_item_name": "테스트 아이템",
        "naver_biz_item_id": "999",
        "business_name": "테스트 업체",
        "naver_business_id": "888",
        "business_type_id": 13,
    }
    defaults.update(kwargs)
    return defaults


class TestGetMonitoringQueueNamedAccess:

    def test_get_monitoring_queue_right_named_row(self, queue_client):
        """R: 이름 기반 row에서 schedule/url/name/interval이 올바르게 생성됨"""
        fake_row = _make_mapping_row(
            naver_biz_item_id="6309731",
            naver_business_id="1630978",
            business_type_id=13,
            biz_item_name="올리브영 예약",
            business_name="올리브영N성수",
        )
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [fake_row]

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        item = items[0]
        assert item["biz_item_name"] == "올리브영 예약"
        assert item["business_name"] == "올리브영N성수"
        assert "/booking/13/bizes/1630978/items/6309731" in item["url"]

    def test_get_monitoring_queue_boundary_empty_returns_empty_list(self, queue_client):
        """B: 결과 없으면 빈 리스트 반환"""
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = []

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_monitoring_queue_error_db_exception_raises_http_500(self, queue_client):
        """E: DB 예외 시 HTTPException(500) 발생"""
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB down")

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 500

    def test_get_monitoring_queue_reference_custom_interval_precedence(self, queue_client):
        """Re: custom_interval이 있으면 interval보다 우선 사용됨"""
        fake_row = _make_mapping_row(interval=60, custom_interval=30)
        mock_db = MagicMock()
        mock_db.execute.return_value.mappings.return_value.all.return_value = [fake_row]

        with patch("app.routes.system.SessionLocal", return_value=mock_db):
            resp = queue_client.get("/api/v1/system/queue")

        assert resp.status_code == 200
        items = resp.json()
        assert items[0]["interval"] == 30
