from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy import text

from app.modules.slide_scanner.services.mobile_handoff import handoff_item_to_slides


def _make_image(path: Path) -> None:
    image = Image.new("RGB", (64, 64), color=(100, 120, 140))
    image.save(path, format="JPEG")


def _insert_mobile_item(
    db,
    *,
    pc_inbox_path: str,
    approval_status: str,
    remote_delete_status: str,
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
                'phone-a',
                'FAKE001',
                'handoff.jpg',
                '/sdcard/DCIM/Camera/handoff.jpg',
                '2026-04-03T10:00:00+00:00',
                1000,
                :pc_inbox_path,
                '2026-04-03T10:00:00+00:00',
                '2026-04-03T10:01:00+00:00',
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


def test_handoff_item_to_slides_R_creates_slide(slide_scanner_session, slide_scanner_test_dirs: dict[str, Path], tmp_path: Path):
    inbox_image = tmp_path / "handoff.jpg"
    _make_image(inbox_image)

    item_id = _insert_mobile_item(
        slide_scanner_session,
        pc_inbox_path=str(inbox_image),
        approval_status="APPROVED",
        remote_delete_status="DONE",
    )

    slide_id = handoff_item_to_slides(slide_scanner_session, item_id)

    assert slide_id > 0
    row = slide_scanner_session.execute(
        text("SELECT id, status, source_app, source_device_id FROM slides WHERE id = :id"),
        {"id": slide_id},
    ).fetchone()
    assert row is not None
    assert row.status == "PENDING"
    assert row.source_app == "mobile:phone-a"
    assert row.source_device_id == "phone-a"


def test_handoff_item_to_slides_E_requires_delete_done(slide_scanner_session, tmp_path: Path):
    inbox_image = tmp_path / "handoff_pending.jpg"
    _make_image(inbox_image)

    item_id = _insert_mobile_item(
        slide_scanner_session,
        pc_inbox_path=str(inbox_image),
        approval_status="APPROVED",
        remote_delete_status="PENDING",
    )

    try:
        handoff_item_to_slides(slide_scanner_session, item_id)
    except ValueError as exc:
        assert "Remote delete is not completed" in str(exc)
    else:
        raise AssertionError("Expected ValueError for remote_delete_status != DONE")


def test_handoff_item_to_slides_Re_slide_link_persisted(slide_scanner_session, tmp_path: Path):
    inbox_image = tmp_path / "handoff_link.jpg"
    _make_image(inbox_image)

    item_id = _insert_mobile_item(
        slide_scanner_session,
        pc_inbox_path=str(inbox_image),
        approval_status="APPROVED",
        remote_delete_status="DONE",
    )

    slide_id = handoff_item_to_slides(slide_scanner_session, item_id)

    row = slide_scanner_session.execute(
        text("SELECT slide_id, handoff_status, local_cleanup_status FROM mobile_ingest_items WHERE id = :id"),
        {"id": item_id},
    ).fetchone()
    assert row.slide_id == slide_id
    assert row.handoff_status == "DONE"
    assert row.local_cleanup_status == "DONE"

