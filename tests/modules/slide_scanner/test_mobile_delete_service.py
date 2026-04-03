from __future__ import annotations

from sqlalchemy import text

from app.modules.slide_scanner.services.mobile_delete import (
    is_allowed_remote_path,
    process_remote_delete_for_item,
)


def test_is_allowed_remote_path_R_camera_path_allowed():
    allowed_roots = ("/sdcard/DCIM/Camera", "/sdcard/Pictures", "/sdcard/Download")

    ok = is_allowed_remote_path(
        "/sdcard/DCIM/Camera/IMG_0010.jpg",
        allowed_roots,
    )

    assert ok is True


def test_is_allowed_remote_path_E_path_injection_blocked():
    allowed_roots = ("/sdcard/DCIM/Camera", "/sdcard/Pictures", "/sdcard/Download")

    ok = is_allowed_remote_path(
        "/sdcard/DCIM/Camera/IMG_0010.jpg;rm -rf /",
        allowed_roots,
    )

    assert ok is False


def test_delete_remote_images_B_idempotent_done_skip(slide_scanner_session):
    slide_scanner_session.execute(
        text(
            """
            INSERT INTO mobile_ingest_items (
                device_id,
                device_serial,
                original_filename,
                source_uri,
                source_mtime_utc,
                source_size_bytes,
                pc_inbox_path,
                captured_at_utc,
                ingested_at,
                approval_status,
                remote_delete_status
            ) VALUES (
                :device_id,
                :device_serial,
                :original_filename,
                :source_uri,
                :source_mtime_utc,
                :source_size_bytes,
                :pc_inbox_path,
                :captured_at_utc,
                :ingested_at,
                :approval_status,
                :remote_delete_status
            )
            """
        ),
        {
            "device_id": "pixel-a",
            "device_serial": "ABC123",
            "original_filename": "IMG_0099.jpg",
            "source_uri": "/sdcard/DCIM/Camera/IMG_0099.jpg",
            "source_mtime_utc": "2026-04-03T11:00:00+00:00",
            "source_size_bytes": 1000,
            "pc_inbox_path": r"D:\tmp\mobile_inbox\ABC123\IMG_0099.jpg",
            "captured_at_utc": "2026-04-03T11:00:00+00:00",
            "ingested_at": "2026-04-03T11:01:00+00:00",
            "approval_status": "APPROVED",
            "remote_delete_status": "DONE",
        },
    )
    item_id = slide_scanner_session.execute(text("SELECT last_insert_rowid()")).scalar_one()
    slide_scanner_session.commit()

    result = process_remote_delete_for_item(
        db=slide_scanner_session,
        item_id=int(item_id),
        adb_path="adb",
        allowed_roots=("/sdcard/DCIM/Camera", "/sdcard/Pictures", "/sdcard/Download"),
    )

    assert result["status"] == "skipped_done"
    assert result["item_id"] == int(item_id)

