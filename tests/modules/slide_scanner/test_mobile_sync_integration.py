from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services.mobile_sync import run_sync_once


def test_mobile_sync_integration_pull_and_register(
    slide_scanner_session,
    fake_adb_path: Path,
    fake_adb_add_remote_file,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_path)

    remote_path = "/sdcard/DCIM/Camera/IMG_SYNC_A.jpg"
    fake_adb_add_remote_file("FAKE001", remote_path, b"sync-a")

    result = run_sync_once(slide_scanner_session)

    assert result["status"] == "ok"
    assert result["pulled"] == 1
    assert result["inserted"] == 1
    assert result["failed"] == 0

    row = slide_scanner_session.execute(
        text(
            """
            SELECT device_serial, source_uri, original_filename, pc_inbox_path
            FROM mobile_ingest_items
            WHERE source_uri = :source_uri
            """
        ),
        {"source_uri": remote_path},
    ).fetchone()
    assert row is not None
    assert row.device_serial == "FAKE001"
    assert row.original_filename == "IMG_SYNC_A.jpg"
    assert Path(str(row.pc_inbox_path)).exists()


def test_mobile_sync_integration_same_filename_separated_by_device(
    slide_scanner_session,
    fake_adb_path: Path,
    fake_adb_add_remote_file,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_path)

    shared_remote_path = "/sdcard/DCIM/Camera/IMG_SAME_NAME.jpg"
    fake_adb_add_remote_file("FAKE001", shared_remote_path, b"from-device-a")
    fake_adb_add_remote_file("FAKE002", shared_remote_path, b"from-device-b")

    result = run_sync_once(slide_scanner_session)

    assert result["status"] == "ok"
    assert result["pulled"] == 2
    assert result["inserted"] == 2
    assert result["failed"] == 0

    rows = slide_scanner_session.execute(
        text(
            """
            SELECT device_serial, pc_inbox_path
            FROM mobile_ingest_items
            WHERE original_filename = 'IMG_SAME_NAME.jpg'
            ORDER BY device_serial
            """
        )
    ).fetchall()
    assert len(rows) == 2
    assert rows[0].device_serial == "FAKE001"
    assert rows[1].device_serial == "FAKE002"
    assert rows[0].pc_inbox_path != rows[1].pc_inbox_path
    assert "FAKE001" in str(rows[0].pc_inbox_path)
    assert "FAKE002" in str(rows[1].pc_inbox_path)
