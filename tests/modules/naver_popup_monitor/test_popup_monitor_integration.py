import json
from types import SimpleNamespace

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
from app.worker.popup_monitor_worker import PopupMonitorWorker


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
def worker_session_factory():
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
async def test_popup_monitor_worker_loop_accumulates_runs_and_detects_new(
    worker_session_factory,
    monkeypatch,
):
    db = worker_session_factory()
    monitor = PopupUrlMonitor(
        name="worker-integration",
        url="https://pcmap.place.naver.com/popupstore/list",
        request_profile="A",
        fallback_strategy="reinforce",
        proxy_enabled=False,
        notify_on_new=True,
        min_new_count=1,
        monitoring_mode="anonymous",
        is_enabled=True,
    )
    db.add(monitor)
    db.commit()
    monitor_id = monitor.id
    db.close()

    html_first = _build_apollo_html(
        [
            {
                "popupId": "first",
                "title": "첫 번째 팝업",
                "placeName": "성수",
                "startDate": "2026-04-20",
                "endDate": "2026-04-30",
            }
        ]
    )
    html_second = _build_apollo_html(
        [
            {
                "popupId": "first",
                "title": "첫 번째 팝업",
                "placeName": "성수",
                "startDate": "2026-04-20",
                "endDate": "2026-04-30",
            },
            {
                "popupId": "second",
                "title": "두 번째 팝업",
                "placeName": "홍대",
                "startDate": "2026-04-21",
                "endDate": "2026-05-01",
            },
        ]
    )
    fetcher = SequenceFetcher(
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
                proxy_url=None,
                fallback_applied=True,
            ),
        ]
    )
    notification = SimpleNamespace(should_notify=lambda state: False)
    service = PopupMonitorService(fetcher=fetcher, notification_service=notification)

    worker = PopupMonitorWorker(browser_manager=None)
    worker._monitor_service = service
    monkeypatch.setattr("app.worker.popup_monitor_worker.SessionLocal", worker_session_factory)

    await worker._main_loop_iteration()
    await worker._main_loop_iteration()

    verify_db = worker_session_factory()
    runs = (
        verify_db.query(PopupUrlMonitorRun)
        .filter(PopupUrlMonitorRun.monitor_id == monitor_id)
        .order_by(PopupUrlMonitorRun.id.asc())
        .all()
    )
    refreshed_monitor = (
        verify_db.query(PopupUrlMonitor)
        .filter(PopupUrlMonitor.id == monitor_id)
        .first()
    )

    assert len(runs) == 2
    assert runs[0].new_count == 1
    assert runs[1].new_count == 1
    assert runs[1].has_new is True
    assert refreshed_monitor is not None
    assert refreshed_monitor.latest_checked_at is not None
    assert refreshed_monitor.latest_snapshot_hash is not None
    assert fetcher.calls == 2

    verify_db.close()
    await worker._cleanup()
