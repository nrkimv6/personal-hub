from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.modules.slide_scanner.services.mobile_ingest import register_ingested_items, resolve_captured_at


def test_register_ingested_items_R_insert_new_rows(slide_scanner_session):
    item = {
        "device_id": "pixel-a",
        "device_serial": "ABC123",
        "original_filename": "IMG_0001.jpg",
        "source_uri": "/sdcard/DCIM/Camera/IMG_0001.jpg",
        "source_mtime_utc": "2026-04-03T10:00:00+00:00",
        "source_size_bytes": 12345,
        "source_sha256": "sha256-1",
        "pc_inbox_path": r"D:\tmp\mobile_inbox\ABC123\IMG_0001.jpg",
        "ingested_at": datetime(2026, 4, 3, 10, 5, 0, tzinfo=timezone.utc),
    }

    result = register_ingested_items(slide_scanner_session, [item])

    assert result["inserted"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0

    inserted = slide_scanner_session.execute(
        text("SELECT COUNT(*) FROM mobile_ingest_items"),
    ).scalar_one()
    assert inserted == 1


def test_register_ingested_items_B_duplicate_key_skipped(slide_scanner_session):
    base_item = {
        "device_id": "pixel-a",
        "device_serial": "ABC123",
        "original_filename": "IMG_0002.jpg",
        "source_uri": "/sdcard/DCIM/Camera/IMG_0002.jpg",
        "source_mtime_utc": "2026-04-03T11:00:00+00:00",
        "source_size_bytes": 9999,
        "source_sha256": "sha256-2",
        "pc_inbox_path": r"D:\tmp\mobile_inbox\ABC123\IMG_0002.jpg",
        "ingested_at": datetime(2026, 4, 3, 11, 1, 0, tzinfo=timezone.utc),
    }

    result = register_ingested_items(slide_scanner_session, [base_item, dict(base_item)])

    assert result["inserted"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 0


def test_resolve_captured_at_O_priority_exif_over_mtime():
    ingested_at = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    # mtime: 2026-04-03T09:00:00Z
    file_mtime = datetime(2026, 4, 3, 9, 0, 0, tzinfo=timezone.utc).timestamp()
    exif = "2026:04:03 08:30:00"

    captured_at = resolve_captured_at(exif_dt=exif, file_mtime=file_mtime, ingested_at=ingested_at)

    assert captured_at == datetime(2026, 4, 3, 8, 30, 0, tzinfo=timezone.utc)

