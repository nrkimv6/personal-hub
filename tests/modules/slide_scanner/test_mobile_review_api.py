from __future__ import annotations

from pathlib import Path

from sqlalchemy import text


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
):
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


def test_get_mobile_review_items_R_pending_sorted_desc(slide_scanner_client, slide_scanner_session, tmp_path: Path):
    path_a = tmp_path / "a.jpg"
    path_b = tmp_path / "b.jpg"
    path_a.write_bytes(b"a")
    path_b.write_bytes(b"b")

    id_old = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="old.jpg",
        source_uri="/sdcard/DCIM/Camera/old.jpg",
        pc_inbox_path=str(path_a),
        captured_at_utc="2026-04-03T09:00:00+00:00",
    )
    id_new = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-b",
        device_serial="FAKE002",
        original_filename="new.jpg",
        source_uri="/sdcard/DCIM/Camera/new.jpg",
        pc_inbox_path=str(path_b),
        captured_at_utc="2026-04-03T10:00:00+00:00",
    )

    response = slide_scanner_client.get("/api/v1/ss/mobile-review/items")
    assert response.status_code == 200
    payload = response.json()
    ids = [item["id"] for item in payload["items"]]
    assert ids[0] == id_new
    assert ids[1] == id_old


def test_get_mobile_review_image_E_missing_file_404(slide_scanner_client, slide_scanner_session):
    item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="missing.jpg",
        source_uri="/sdcard/DCIM/Camera/missing.jpg",
        pc_inbox_path=r"D:\not-found\missing.jpg",
        captured_at_utc="2026-04-03T11:00:00+00:00",
    )

    response = slide_scanner_client.get(f"/api/v1/ss/mobile-review/{item_id}/image")
    assert response.status_code == 404


def test_reject_mobile_item_Ca_reason_persisted(slide_scanner_client, slide_scanner_session, tmp_path: Path):
    image_path = tmp_path / "reject.jpg"
    image_path.write_bytes(b"reject")

    item_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="reject.jpg",
        source_uri="/sdcard/DCIM/Camera/reject.jpg",
        pc_inbox_path=str(image_path),
        captured_at_utc="2026-04-03T12:00:00+00:00",
    )

    response = slide_scanner_client.post(
        f"/api/v1/ss/mobile-review/{item_id}/reject",
        json={"reason": "blurred and out of frame"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["approval_status"] == "REJECTED"

    row = slide_scanner_session.execute(
        text("SELECT approval_status, error_message FROM mobile_ingest_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    assert row.approval_status == "REJECTED"
    assert row.error_message == "blurred and out of frame"

