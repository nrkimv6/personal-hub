from __future__ import annotations

from io import BytesIO

from PIL import Image
from sqlalchemy import text

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.services.mobile_sync import run_sync_once


def _make_jpeg_bytes() -> bytes:
    image = Image.new("RGB", (80, 60), color=(120, 80, 180))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _insert_mobile_item(
    db,
    *,
    approval_status: str,
    remote_delete_status: str,
    pc_inbox_path: str,
) -> int:
    db.execute(
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
                'phone-z',
                'FAKE001',
                'blocked.jpg',
                '/sdcard/DCIM/Camera/blocked.jpg',
                '2026-04-03T12:00:00+00:00',
                200,
                :pc_inbox_path,
                '2026-04-03T12:00:00+00:00',
                '2026-04-03T12:00:01+00:00',
                :approval_status,
                :remote_delete_status
            )
            """
        ),
        {
            "pc_inbox_path": pc_inbox_path,
            "approval_status": approval_status,
            "remote_delete_status": remote_delete_status,
        },
    )
    item_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()
    db.commit()
    return int(item_id)


def test_mobile_review_integration_handoff_requires_delete_done(
    slide_scanner_client,
    slide_scanner_session,
    fake_adb_path,
    fake_adb_add_remote_file,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_path)

    remote_path = "/sdcard/DCIM/Camera/IMG_PIPELINE.jpg"
    fake_adb_add_remote_file("FAKE001", remote_path, _make_jpeg_bytes())
    sync_result = run_sync_once(slide_scanner_session)
    assert sync_result["inserted"] == 1

    item_id = slide_scanner_session.execute(
        text("SELECT id FROM mobile_ingest_items WHERE source_uri = :source_uri"),
        {"source_uri": remote_path},
    ).scalar_one()

    approve_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/approve")
    assert approve_response.status_code == 200

    delete_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "done"

    handoff_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    assert handoff_payload["slide_id"] > 0

    row = slide_scanner_session.execute(
        text("SELECT handoff_status, local_cleanup_status, slide_id FROM mobile_ingest_items WHERE id = :item_id"),
        {"item_id": item_id},
    ).fetchone()
    assert row.handoff_status == "DONE"
    assert row.local_cleanup_status == "DONE"
    assert row.slide_id == handoff_payload["slide_id"]


def test_mobile_review_integration_handoff_blocked_on_delete_failed(
    slide_scanner_client,
    slide_scanner_session,
    tmp_path,
):
    image_path = tmp_path / "blocked.jpg"
    image_path.write_bytes(_make_jpeg_bytes())
    item_id = _insert_mobile_item(
        slide_scanner_session,
        approval_status="APPROVED",
        remote_delete_status="FAILED",
        pc_inbox_path=str(image_path),
    )

    response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert response.status_code == 409
    assert "remote_delete_status=DONE" in response.json()["detail"]
