from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.modules.slide_scanner.routers import mobile_review as mobile_review_router


def _insert_mobile_item(
    db,
    *,
    device_id: str,
    device_serial: str,
    original_filename: str,
    source_uri: str,
    pc_inbox_path: str,
    captured_at_utc: str,
    approval_status: str = "PENDING",
    remote_delete_status: str = "PENDING",
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
            "device_id": device_id,
            "device_serial": device_serial,
            "original_filename": original_filename,
            "source_uri": source_uri,
            "source_mtime_utc": captured_at_utc,
            "source_size_bytes": 100,
            "pc_inbox_path": pc_inbox_path,
            "captured_at_utc": captured_at_utc,
            "ingested_at": captured_at_utc,
            "approval_status": approval_status,
            "remote_delete_status": remote_delete_status,
        },
    )
    item_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()
    db.commit()
    return int(item_id)


def test_state_transition_Co_only_pending_to_approved_or_rejected(
    slide_scanner_client,
    slide_scanner_session,
    tmp_path: Path,
):
    approved_path = tmp_path / "approved.jpg"
    rejected_path = tmp_path / "rejected.jpg"
    approved_path.write_bytes(b"a")
    rejected_path.write_bytes(b"b")

    approve_item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="approved.jpg",
        source_uri="/sdcard/DCIM/Camera/approved.jpg",
        pc_inbox_path=str(approved_path),
        captured_at_utc="2026-04-03T09:00:00+00:00",
    )
    reject_item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-b",
        device_serial="FAKE002",
        original_filename="rejected.jpg",
        source_uri="/sdcard/DCIM/Camera/rejected.jpg",
        pc_inbox_path=str(rejected_path),
        captured_at_utc="2026-04-03T09:01:00+00:00",
    )

    approve_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{approve_item_id}/approve")
    assert approve_response.status_code == 200

    duplicate_approve_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{approve_item_id}/approve")
    assert duplicate_approve_response.status_code == 409

    reject_response = slide_scanner_client.post(
        f"/api/v1/ss/mobile-review/{reject_item_id}/reject",
        json={"reason": "not a slide"},
    )
    assert reject_response.status_code == 200

    duplicate_reject_response = slide_scanner_client.post(
        f"/api/v1/ss/mobile-review/{reject_item_id}/reject",
        json={"reason": "duplicate"},
    )
    assert duplicate_reject_response.status_code == 409


def test_state_transition_O_approve_before_remote_delete_before_handoff(
    slide_scanner_client,
    slide_scanner_session,
    tmp_path: Path,
    monkeypatch,
):
    image_path = tmp_path / "ordered.jpg"
    image_path.write_bytes(b"ordered")
    item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="ordered.jpg",
        source_uri="/sdcard/DCIM/Camera/ordered.jpg",
        pc_inbox_path=str(image_path),
        captured_at_utc="2026-04-03T10:00:00+00:00",
        approval_status="PENDING",
        remote_delete_status="PENDING",
    )

    def _fake_remote_delete(*, db, item_id: int, adb_path, allowed_roots):
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
        return {"status": "done", "item_id": item_id, "results": {"/sdcard/DCIM/Camera/ordered.jpg": True}}

    monkeypatch.setattr(mobile_review_router, "process_remote_delete_for_item", _fake_remote_delete)
    monkeypatch.setattr(mobile_review_router, "handoff_item_to_slides", lambda _db, _item_id: 777)

    before_approve = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete")
    assert before_approve.status_code == 409

    approve_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/approve")
    assert approve_response.status_code == 200

    before_delete_handoff = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert before_delete_handoff.status_code == 409

    delete_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "done"

    handoff_response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert handoff_response.status_code == 200
    assert handoff_response.json()["slide_id"] == 777


def test_state_transition_E_handoff_without_remote_delete_blocked(
    slide_scanner_client,
    slide_scanner_session,
    tmp_path: Path,
):
    image_path = tmp_path / "blocked.jpg"
    image_path.write_bytes(b"blocked")
    item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="blocked.jpg",
        source_uri="/sdcard/DCIM/Camera/blocked.jpg",
        pc_inbox_path=str(image_path),
        captured_at_utc="2026-04-03T11:00:00+00:00",
        approval_status="APPROVED",
        remote_delete_status="FAILED",
    )

    response = slide_scanner_client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert response.status_code == 409
    assert "remote_delete_status=DONE" in response.json()["detail"]
