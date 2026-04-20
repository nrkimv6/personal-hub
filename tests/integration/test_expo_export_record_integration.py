"""Expo export record 파일시스템/집계 통합 테스트."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.models import CrawledPage, CrawlRequest, Event, InstagramWorkerStatus, Popup
from app.schemas.expo import ExpoExportBooth, ExpoExportPayload, ExpoExportPin
from app.services.expo_service import ExpoService
from app.shared.io.json_store import read_json


def _payload(exported_at: str, version: str = "2026-04-20") -> ExpoExportPayload:
    return ExpoExportPayload(
        version=version,
        slug="coffee-expo-2026",
        title="커피엑스포 2026",
        exported_at=datetime.fromisoformat(exported_at),
        booths=[
            ExpoExportBooth(
                id="A-09",
                name="A-09",
                pin=ExpoExportPin(xNorm=0.12, yNorm=0.34),
            )
        ],
    )


def test_record_export_writes_json_atomically(tmp_path, monkeypatch, test_db_session):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    service = ExpoService(test_db_session)

    service.record_export("coffee-expo-2026", _payload("2026-04-20T15:00:00+09:00"))

    export_dir = Path(tmp_path) / "expo" / "coffee-expo-2026"
    record_path = export_dir / "export-record.json"
    assert record_path.exists()
    assert list(export_dir.glob(".*.tmp")) == []

    payload = read_json(record_path, default={})
    assert payload["slug"] == "coffee-expo-2026"
    assert payload["booth_count"] == 1


def test_record_export_overwrites_latest_payload(tmp_path, monkeypatch, test_db_session):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    service = ExpoService(test_db_session)

    service.record_export("coffee-expo-2026", _payload("2026-04-20T15:00:00+09:00", version="2026-04-20"))
    service.record_export("coffee-expo-2026", _payload("2026-04-20T16:00:00+09:00", version="2026-04-20.1"))

    record_path = Path(tmp_path) / "expo" / "coffee-expo-2026" / "export-record.json"
    payload = read_json(record_path, default={})
    assert payload["version"] == "2026-04-20.1"
    assert payload["exported_at"] == "2026-04-20T16:00:00+09:00"


def test_pipeline_and_collection_status_aggregate_db_rows(tmp_path, monkeypatch, test_db_session):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    service = ExpoService(test_db_session)

    event = Event(
        title="Expo Event",
        event_type="event",
        event_start=date(2026, 4, 15),
        event_end=date(2026, 4, 18),
        source_type="manual",
    )
    popup = Popup(
        title="Expo Popup",
        start_date=date(2026, 4, 15),
        end_date=date(2026, 4, 18),
        source_type="manual",
    )
    test_db_session.add_all([event, popup])
    test_db_session.flush()

    crawled_page = CrawledPage(
        url="https://example.com/expo-source",
        url_type="naver_blog",
        title="Expo Source",
        crawled_at=datetime(2026, 4, 20, 11, 0, 0),
        is_event=False,
        url_hash="expo-integration-hash",
    )
    crawl_request = CrawlRequest(
        url="https://example.com/expo-source",
        url_type="naver_blog",
        status=CrawlRequest.STATUS_COMPLETED,
        requested_by="manual",
        requested_at=datetime(2026, 4, 20, 10, 0, 0),
        processed_at=datetime(2026, 4, 20, 10, 5, 0),
        result_type="crawled_page",
        result_id=1,
        result_status="created",
    )
    worker = InstagramWorkerStatus(
        worker_id="expo-worker",
        pid=9911,
        started_at=datetime(2026, 4, 20, 9, 0, 0),
        last_heartbeat=datetime(2026, 4, 20, 11, 0, 0),
        current_state="processing",
        is_alive=True,
    )
    test_db_session.add_all([crawled_page, crawl_request, worker])
    test_db_session.commit()
    service.record_export("coffee-expo-2026", _payload("2026-04-20T16:00:00+09:00"))

    with patch(
        "app.modules.instagram.services.worker_status_service.WorkerHealthRedis.check",
        return_value={
            "source": "redis",
            "ttl_remaining": 18,
            "updated_at": datetime(2026, 4, 20, 11, 0, 0),
        },
    ):
        pipeline = service.get_pipeline_status("coffee-expo-2026")
        collection = service.get_collection_status("coffee-expo-2026")

    assert pipeline.event_count == 1
    assert pipeline.popup_count == 1
    assert pipeline.last_export_booth_count == 1
    assert collection.recent_completed_requests == 1
    assert collection.matching_pending_count == 1
    assert collection.recent_sources[0].match_status == "matching_pending"
