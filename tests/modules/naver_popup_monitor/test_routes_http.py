import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.models.base import Base
from app.models.browser_profile import BrowserProfile
from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.popup_url_monitor_run import PopupUrlMonitorRun
from app.models.service_account import ServiceAccount
from app.modules.naver_popup_monitor.services.fetcher import PopupFetchResult
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService
from app.modules.naver_popup_monitor.routes import monitor as monitor_routes


def _build_apollo_html(items: list[dict]) -> str:
    apollo = {
        "ROOT_QUERY": {
            "popupStoreList": [f"PopupStore:{item['popupId']}" for item in items],
        }
    }
    for item in items:
        apollo[f"PopupStore:{item['popupId']}"] = {
            "__typename": "PopupStore",
            "popupId": item["popupId"],
            "title": item["title"],
            "placeName": item.get("placeName"),
            "startDate": item.get("startDate"),
            "endDate": item.get("endDate"),
            "bookingUrl": item.get("bookingUrl"),
        }
    return (
        "<html><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo, ensure_ascii=False)}"
        "</script></body></html>"
    )


class SequenceFetcher:
    def __init__(self, results: list[PopupFetchResult]):
        self._results = results
        self.calls = 0

    async def fetch_popup_html(self, **kwargs):
        idx = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[idx]

    async def close(self):
        return None


@pytest.fixture
def popup_http_context(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            BrowserProfile.__table__,
            ServiceAccount.__table__,
            PopupUrlMonitor.__table__,
            PopupUrlMonitorRun.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=True)

    html = _build_apollo_html(
        [
            {
                "popupId": "http-case-1",
                "title": "HTTP 테스트 팝업",
                "placeName": "성수",
                "startDate": "2026-05-01",
                "endDate": "2026-05-10",
                "bookingUrl": "https://booking.naver.com/example",
            }
        ]
    )
    service = PopupMonitorService(
        fetcher=SequenceFetcher(
            [
                PopupFetchResult(
                    success=True,
                    html=html,
                    status=200,
                    final_url="https://pcmap.place.naver.com/popupstore/list",
                    request_profile="A",
                    proxy_url=None,
                    fallback_applied=False,
                )
            ]
        ),
        notification_service=SimpleNamespace(should_notify=lambda state: False),
    )
    monkeypatch.setattr(monitor_routes, "monitor_service", service)

    app = FastAPI()

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(monitor_routes.router)

    with TestClient(app) as client:
        yield client, factory

    engine.dispose()


def _create_service_account(factory, service_type: str) -> int:
    db = factory()
    try:
        profile = BrowserProfile(
            name=f"test-{service_type}",
            profile_dir=f"test_{service_type}_{uuid.uuid4().hex[:8]}",
        )
        db.add(profile)
        db.flush()

        account = ServiceAccount(
            profile_id=profile.id,
            service_type=service_type,
            identifier=f"{service_type}@test.local",
            is_logged_in=True,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account.id
    finally:
        db.close()


def test_popup_monitor_http_crud_enable_disable_check_now_latest_runs(popup_http_context):
    client, factory = popup_http_context
    naver_account_id = _create_service_account(factory, "naver")

    create_payload = {
        "name": "HTTP CRUD 모니터",
        "url": "https://pcmap.place.naver.com/popupstore/list",
        "request_profile": "A",
        "fallback_strategy": "reinforce",
        "proxy_enabled": False,
        "notify_on_new": True,
        "min_new_count": 1,
        "monitoring_mode": "anonymous",
        "service_account_id": naver_account_id,
        "browser_fallback_enabled": False,
        "is_enabled": True,
    }

    create_res = client.post("/api/v1/naver-popup/monitors", json=create_payload)
    assert create_res.status_code == 201
    created = create_res.json()
    monitor_id = created["id"]
    assert created["service_account_id"] == naver_account_id
    assert created["request_profile"] == "A"

    list_res = client.get("/api/v1/naver-popup/monitors")
    assert list_res.status_code == 200
    assert any(item["id"] == monitor_id for item in list_res.json())

    get_res = client.get(f"/api/v1/naver-popup/monitors/{monitor_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "HTTP CRUD 모니터"

    update_res = client.put(
        f"/api/v1/naver-popup/monitors/{monitor_id}",
        json={
            "name": "HTTP CRUD 모니터 수정",
            "request_profile": "B",
            "proxy_enabled": True,
            "min_new_count": 2,
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["name"] == "HTTP CRUD 모니터 수정"
    assert updated["request_profile"] == "B"
    assert updated["proxy_enabled"] is True
    assert updated["min_new_count"] == 2

    disable_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/disable")
    assert disable_res.status_code == 200
    assert disable_res.json()["is_enabled"] is False

    enable_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/enable")
    assert enable_res.status_code == 200
    assert enable_res.json()["is_enabled"] is True

    check_res = client.post(f"/api/v1/naver-popup/monitors/{monitor_id}/check-now")
    assert check_res.status_code == 202
    check_payload = check_res.json()
    assert check_payload["monitor_id"] == monitor_id
    assert check_payload["run_id"] > 0
    assert check_payload["status"] in {"success", "partial"}

    latest_res = client.get(f"/api/v1/naver-popup/monitors/{monitor_id}/latest")
    assert latest_res.status_code == 200
    latest_payload = latest_res.json()
    assert latest_payload["monitor_id"] == monitor_id
    assert latest_payload["item_count"] == 1
    assert latest_payload["last_run"]["id"] == check_payload["run_id"]

    runs_res = client.get(f"/api/v1/naver-popup/monitors/{monitor_id}/runs?limit=10")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 1
    assert runs[0]["id"] == check_payload["run_id"]

    delete_res = client.delete(f"/api/v1/naver-popup/monitors/{monitor_id}")
    assert delete_res.status_code == 200
    assert delete_res.json()["deleted"] == monitor_id


def test_popup_monitor_http_error_responses(popup_http_context):
    client, factory = popup_http_context

    invalid_account_res = client.post(
        "/api/v1/naver-popup/monitors",
        json={
            "url": "https://pcmap.place.naver.com/popupstore/list",
            "service_account_id": 999999,
        },
    )
    assert invalid_account_res.status_code == 400

    instagram_account_id = _create_service_account(factory, "instagram")
    wrong_type_res = client.post(
        "/api/v1/naver-popup/monitors",
        json={
            "url": "https://pcmap.place.naver.com/popupstore/list",
            "service_account_id": instagram_account_id,
        },
    )
    assert wrong_type_res.status_code == 400

    for method, path in [
        ("get", "/api/v1/naver-popup/monitors/99999"),
        ("post", "/api/v1/naver-popup/monitors/99999/enable"),
        ("post", "/api/v1/naver-popup/monitors/99999/disable"),
        ("post", "/api/v1/naver-popup/monitors/99999/check-now"),
        ("get", "/api/v1/naver-popup/monitors/99999/latest"),
        ("get", "/api/v1/naver-popup/monitors/99999/runs"),
        ("delete", "/api/v1/naver-popup/monitors/99999"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404
