import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.browser_profile import BrowserProfile
from app.models.popup_url_monitor import PopupUrlMonitor
from app.models.popup_url_monitor_run import PopupUrlMonitorRun
from app.models.service_account import ServiceAccount
from app.modules.naver_popup_monitor.services.fetcher import PopupFetchResult
from app.modules.naver_popup_monitor.services.monitor_service import PopupMonitorService


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
            "placeName": item.get("placeName", "unknown"),
            "startDate": item.get("startDate"),
            "endDate": item.get("endDate"),
            "bookingUrl": item.get("bookingUrl"),
        }
    return (
        "<html><body><script>"
        f"window.__APOLLO_STATE__ = {json.dumps(apollo, ensure_ascii=False)}"
        "</script></body></html>"
    )


class FakeFetcher:
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
def integration_session_factory():
    from app.models.base import Base

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
    yield factory
    engine.dispose()


@pytest.mark.asyncio
async def test_monitor_service_updates_latest_runs_and_notification_condition(
    integration_session_factory,
):
    db = integration_session_factory()
    monitor = PopupUrlMonitor(
        name="팝업 테스트",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=True,
        notify_on_new=True,
        min_new_count=2,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    html_first = _build_apollo_html(
        [
            {
                "popupId": "p1",
                "title": "팝업1",
                "placeName": "성수",
                "startDate": "2026-04-10",
                "endDate": "2026-04-20",
            }
        ]
    )
    html_second = _build_apollo_html(
        [
            {
                "popupId": "p1",
                "title": "팝업1",
                "placeName": "성수",
                "startDate": "2026-04-10",
                "endDate": "2026-04-20",
            },
            {
                "popupId": "p2",
                "title": "팝업2",
                "placeName": "홍대",
                "startDate": "2026-04-11",
                "endDate": "2026-04-21",
            },
        ]
    )

    fake_fetcher = FakeFetcher(
        [
            PopupFetchResult(
                success=True,
                html=html_first,
                status=200,
                final_url="https://pcmap.place.naver.com/popupstore/list",
                request_profile="A",
                proxy_url=None,
                fallback_applied=False,
            ),
            PopupFetchResult(
                success=True,
                html=html_second,
                status=200,
                final_url="https://pcmap.place.naver.com/popupstore/list",
                request_profile="B",
                proxy_url="http://proxy.local:8080",
                fallback_applied=True,
            ),
        ]
    )
    notification = MagicMock()
    notification.should_notify.return_value = True
    notification.send_notification_message = AsyncMock()
    service = PopupMonitorService(
        fetcher=fake_fetcher,
        notification_service=notification,
    )

    outcome1 = await service.run_monitor_once(db, monitor, trigger="manual")
    assert outcome1.new_count == 1
    notification.send_notification_message.assert_not_called()

    monitor.min_new_count = 1
    db.commit()

    outcome2 = await service.run_monitor_once(db, monitor, trigger="manual")
    assert outcome2.new_count == 1
    assert outcome2.proxy_url == "http://proxy.local:8080"
    assert outcome2.fallback_applied is True

    runs_payload = service.list_runs_payload(db, monitor.id, limit=10)
    assert len(runs_payload) == 2
    assert runs_payload[0]["request_profile"] == "B"

    latest_payload = service.get_latest_payload(db, monitor.id)
    assert latest_payload["item_count"] == 2
    assert latest_payload["last_run"]["new_count"] == 1
    notification.send_notification_message.assert_called_once()
    db.close()
