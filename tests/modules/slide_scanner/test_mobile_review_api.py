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
    handoff_status: str = "PENDING",
    slide_id: int | None = None,
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
                remote_delete_status,
                handoff_status,
                slide_id
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
                :remote_delete_status,
                :handoff_status,
                :slide_id
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
            "handoff_status": handoff_status,
            "slide_id": slide_id,
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


def test_get_mobile_review_items_filters_rejected_by_default(slide_scanner_client, slide_scanner_session, tmp_path: Path):
    pending_path = tmp_path / "pending.jpg"
    approved_path = tmp_path / "approved.jpg"
    rejected_path = tmp_path / "rejected.jpg"
    pending_path.write_bytes(b"p")
    approved_path.write_bytes(b"a")
    rejected_path.write_bytes(b"r")

    pending_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="pending.jpg",
        source_uri="/sdcard/DCIM/Camera/pending.jpg",
        pc_inbox_path=str(pending_path),
        captured_at_utc="2026-04-03T10:00:00+00:00",
        approval_status="PENDING",
    )
    approved_id = _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="approved.jpg",
        source_uri="/sdcard/DCIM/Camera/approved.jpg",
        pc_inbox_path=str(approved_path),
        captured_at_utc="2026-04-03T11:00:00+00:00",
        approval_status="APPROVED",
        remote_delete_status="FAILED",
    )
    _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="rejected.jpg",
        source_uri="/sdcard/DCIM/Camera/rejected.jpg",
        pc_inbox_path=str(rejected_path),
        captured_at_utc="2026-04-03T12:00:00+00:00",
        approval_status="REJECTED",
    )

    response = slide_scanner_client.get("/api/v1/ss/mobile-review/items")
    assert response.status_code == 200
    payload = response.json()
    ids = {item["id"] for item in payload["items"]}
    assert ids == {pending_id, approved_id}

    rejected_only = slide_scanner_client.get("/api/v1/ss/mobile-review/items?approval_status=REJECTED")
    assert rejected_only.status_code == 200
    rejected_payload = rejected_only.json()
    assert rejected_payload["total"] == 1
    assert rejected_payload["items"][0]["approval_status"] == "REJECTED"


def test_get_mobile_review_items_action_flags(slide_scanner_client, slide_scanner_session, tmp_path: Path):
    pending_path = tmp_path / "flags_pending.jpg"
    retry_path = tmp_path / "flags_retry.jpg"
    handoff_path = tmp_path / "flags_handoff.jpg"
    open_path = tmp_path / "flags_open.jpg"
    for path, content in (
        (pending_path, b"p"),
        (retry_path, b"r"),
        (handoff_path, b"h"),
        (open_path, b"o"),
    ):
        path.write_bytes(content)

    _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="flags_pending.jpg",
        source_uri="/sdcard/DCIM/Camera/flags_pending.jpg",
        pc_inbox_path=str(pending_path),
        captured_at_utc="2026-04-03T09:00:00+00:00",
        approval_status="PENDING",
    )
    _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="flags_retry.jpg",
        source_uri="/sdcard/DCIM/Camera/flags_retry.jpg",
        pc_inbox_path=str(retry_path),
        captured_at_utc="2026-04-03T09:01:00+00:00",
        approval_status="APPROVED",
        remote_delete_status="FAILED",
    )
    _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="flags_handoff.jpg",
        source_uri="/sdcard/DCIM/Camera/flags_handoff.jpg",
        pc_inbox_path=str(handoff_path),
        captured_at_utc="2026-04-03T09:02:00+00:00",
        approval_status="APPROVED",
        remote_delete_status="DONE",
        handoff_status="PENDING",
    )
    slide_scanner_session.execute(
        text(
            """
            INSERT INTO slides (
                file_name,
                file_path,
                status,
                captured_at,
                source_app,
                thumbnail,
                is_archived
            ) VALUES (
                'flags_open.jpg',
                :file_path,
                'PENDING',
                '2026-04-03T09:03:00+00:00',
                'mobile:phone-a',
                :thumbnail,
                0
            )
            """
        ),
        {
            "file_path": str(open_path),
            "thumbnail": b"thumb-open",
        },
    )
    slide_id = int(slide_scanner_session.execute(text("SELECT last_insert_rowid()")).scalar_one())
    slide_scanner_session.commit()
    _insert_mobile_item(
        slide_scanner_session,
        device_id="phone-a",
        device_serial="FAKE001",
        original_filename="flags_open.jpg",
        source_uri="/sdcard/DCIM/Camera/flags_open.jpg",
        pc_inbox_path=str(open_path),
        captured_at_utc="2026-04-03T09:03:00+00:00",
        approval_status="APPROVED",
        remote_delete_status="DONE",
        handoff_status="DONE",
        slide_id=slide_id,
    )

    response = slide_scanner_client.get("/api/v1/ss/mobile-review/items?approval_status=APPROVED")
    assert response.status_code == 200
    payload = response.json()
    by_name = {item["original_filename"]: item for item in payload["items"]}

    retry_item = by_name["flags_retry.jpg"]
    assert retry_item["can_approve"] is False
    assert retry_item["can_remote_delete"] is True
    assert retry_item["can_handoff"] is False
    assert retry_item["can_open_editor"] is False

    handoff_item = by_name["flags_handoff.jpg"]
    assert handoff_item["can_remote_delete"] is False
    assert handoff_item["can_handoff"] is True
    assert handoff_item["can_open_editor"] is False

    open_item = by_name["flags_open.jpg"]
    assert open_item["slide_id"] == slide_id
    assert open_item["can_handoff"] is False
    assert open_item["can_open_editor"] is True

