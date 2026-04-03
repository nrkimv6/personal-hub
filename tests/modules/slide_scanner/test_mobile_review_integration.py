from __future__ import annotations

from io import BytesIO

from PIL import Image
from sqlalchemy import text

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.routers import mobile_review as mobile_review_module
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
    source_uri: str = "/sdcard/DCIM/Camera/blocked.jpg",
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
                :source_uri,
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
            "source_uri": source_uri,
        },
    )
    item_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()
    db.commit()
    return int(item_id)


def _mark_handoff_done(db, item_id: int, slide_id: int) -> int:
    existing_slide = db.execute(
        text("SELECT id FROM slides WHERE id = :slide_id"),
        {"slide_id": slide_id},
    ).scalar()
    if not existing_slide:
        inbox_path = db.execute(
            text("SELECT pc_inbox_path FROM mobile_ingest_items WHERE id = :item_id"),
            {"item_id": item_id},
        ).scalar_one()
        db.execute(
            text(
                """
                INSERT INTO slides (
                    id,
                    file_name,
                    file_path,
                    status,
                    captured_at,
                    source_app,
                    thumbnail,
                    is_archived
                ) VALUES (
                    :slide_id,
                    'mock-handoff.jpg',
                    :file_path,
                    'PENDING',
                    '2026-04-03T12:00:00+00:00',
                    'mobile:test',
                    :thumbnail,
                    0
                )
                """
            ),
            {
                "slide_id": slide_id,
                "file_path": str(inbox_path),
                "thumbnail": b"thumb",
            },
        )

    db.execute(
        text(
            """
            UPDATE mobile_ingest_items
            SET slide_id = :slide_id,
                handoff_status = 'DONE',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :item_id
            """
        ),
        {
            "item_id": item_id,
            "slide_id": slide_id,
        },
    )
    db.commit()
    return slide_id


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
    assert handoff_payload["can_open_editor"] is True

    second_handoff_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert second_handoff_response.status_code == 200
    second_payload = second_handoff_response.json()
    assert second_payload["slide_id"] == handoff_payload["slide_id"]
    assert second_payload["handoff_status"] == "DONE"

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


def test_mobile_review_integration_retry_delete_then_handoff_success(
    slide_scanner_client,
    slide_scanner_session,
    tmp_path,
    monkeypatch,
):
    image_path = tmp_path / "retry.jpg"
    image_path.write_bytes(_make_jpeg_bytes())
    item_id = _insert_mobile_item(
        slide_scanner_session,
        approval_status="APPROVED",
        remote_delete_status="FAILED",
        pc_inbox_path=str(image_path),
        source_uri="/sdcard/DCIM/Camera/retry.jpg",
    )

    call_count = {"value": 0}

    def _toggle_remote_delete(*, db, item_id: int, adb_path, allowed_roots):
        call_count["value"] += 1
        if call_count["value"] == 1:
            db.execute(
                text(
                    """
                    UPDATE mobile_ingest_items
                    SET remote_delete_status = 'FAILED',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :item_id
                    """
                ),
                {"item_id": item_id},
            )
            db.commit()
            return {"status": "failed", "item_id": item_id, "results": {}, "error": "adb timeout"}

        db.execute(
            text(
                """
                UPDATE mobile_ingest_items
                SET remote_delete_status = 'DONE',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :item_id
                """
            ),
            {"item_id": item_id},
        )
        db.commit()
        return {"status": "done", "item_id": item_id, "results": {"/sdcard/DCIM/Camera/retry.jpg": True}}

    monkeypatch.setattr(mobile_review_module, "process_remote_delete_for_item", _toggle_remote_delete)
    monkeypatch.setattr(
        mobile_review_module,
        "handoff_item_to_slides",
        lambda _db, _item_id: _mark_handoff_done(_db, _item_id, 345),
    )

    first_delete = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete")
    assert first_delete.status_code == 200
    assert first_delete.json()["status"] == "failed"

    retry_delete = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete/retry")
    assert retry_delete.status_code == 200
    assert retry_delete.json()["status"] == "done"

    handoff_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert handoff_response.status_code == 200
    payload = handoff_response.json()
    assert payload["slide_id"] == 345
    assert payload["handoff_status"] == "DONE"
