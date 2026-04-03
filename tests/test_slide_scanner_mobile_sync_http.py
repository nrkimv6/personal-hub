from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.routers import mobile_review as mobile_review_module
from app.modules.slide_scanner.routers import mobile_sync as mobile_sync_module
from app.modules.slide_scanner.routers import mobile_review_router, mobile_sync_router, slides_router


def _apply_sql_file(engine, sql_path: Path) -> None:
    sql_content = sql_path.read_text(encoding="utf-8")
    statements = [segment.strip() for segment in sql_content.split(";") if segment.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _insert_mobile_item(
    db: Session,
    *,
    pc_inbox_path: str,
    approval_status: str = "PENDING",
    remote_delete_status: str = "PENDING",
    handoff_status: str = "PENDING",
    slide_id: int | None = None,
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
                remote_delete_status,
                handoff_status,
                slide_id
            ) VALUES (
                'phone-a',
                'FAKE001',
                'http-case.jpg',
                '/sdcard/DCIM/Camera/http-case.jpg',
                '2026-04-03T12:00:00+00:00',
                200,
                :pc_inbox_path,
                '2026-04-03T12:00:00+00:00',
                '2026-04-03T12:00:01+00:00',
                :approval_status,
                :remote_delete_status,
                :handoff_status,
                :slide_id
            )
            """
        ),
        {
            "pc_inbox_path": pc_inbox_path,
            "approval_status": approval_status,
            "remote_delete_status": remote_delete_status,
            "handoff_status": handoff_status,
            "slide_id": slide_id,
        },
    )
    item_id = db.execute(text("SELECT last_insert_rowid()")).scalar_one()
    db.commit()
    return int(item_id)


def _mark_handoff_done(db: Session, item_id: int, slide_id: int) -> int:
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
            "slide_id": slide_id,
            "item_id": item_id,
        },
    )
    db.commit()
    return slide_id


@pytest.fixture()
def slide_scanner_http_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Session]]:
    db_path = tmp_path / "slide_scanner_http.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    migrations_dir = Path(__file__).resolve().parents[1] / "app" / "modules" / "slide_scanner" / "migrations"
    _apply_sql_file(engine, migrations_dir / "001_initial.sql")
    _apply_sql_file(engine, migrations_dir / "003_aspect_ratio.sql")
    _apply_sql_file(engine, migrations_dir / "004_filters.sql")
    _apply_sql_file(engine, migrations_dir / "005_ocr.sql")
    _apply_sql_file(engine, migrations_dir / "010_mobile_ingest.sql")
    _apply_sql_file(engine, migrations_dir / "011_slides_source_device.sql")

    data_dir = tmp_path / "slide_scanner_data"
    originals_dir = data_dir / "originals"
    output_dir = data_dir / "output"
    inbox_dir = data_dir / "mobile_inbox"
    approved_dir = data_dir / "mobile_approved"
    rejected_dir = data_dir / "mobile_rejected"
    for directory in (data_dir, originals_dir, output_dir, inbox_dir, approved_dir, rejected_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings, "ORIGINALS_DIR", originals_dir)
    monkeypatch.setattr(settings, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(settings, "MOBILE_INBOX_DIR", inbox_dir)
    monkeypatch.setattr(settings, "MOBILE_APPROVED_DIR", approved_dir)
    monkeypatch.setattr(settings, "MOBILE_REJECTED_DIR", rejected_dir)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    app = FastAPI()
    app.include_router(mobile_sync_router, prefix="/api/v1/ss")
    app.include_router(mobile_review_router, prefix="/api/v1/ss")
    app.include_router(slides_router, prefix="/api/v1/ss")

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, session

    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_mobile_sync_run_http_R_returns_ok_counts(slide_scanner_http_context, monkeypatch):
    client, _db = slide_scanner_http_context
    monkeypatch.setattr(
        mobile_sync_module,
        "run_sync_once",
        lambda _session: {
            "status": "ok",
            "pulled": 2,
            "inserted": 2,
            "failed": 0,
        },
    )

    response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["inserted"] == 2


def test_mobile_sync_run_http_E_returns_error_payload(slide_scanner_http_context, monkeypatch):
    client, _db = slide_scanner_http_context
    monkeypatch.setattr(
        mobile_sync_module,
        "run_sync_once",
        lambda _session: {
            "status": "error",
            "error": "adb timeout",
        },
    )

    response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"] == "adb timeout"


def test_mobile_sync_devices_and_review_items_http_R(slide_scanner_http_context, monkeypatch, tmp_path: Path):
    client, db = slide_scanner_http_context
    image_path = tmp_path / "review.jpg"
    image_path.write_bytes(b"review")
    _insert_mobile_item(db, pc_inbox_path=str(image_path))

    monkeypatch.setattr(
        mobile_sync_module,
        "list_connected_devices",
        lambda _adb_path: [{"serial": "FAKE001", "state": "device", "is_online": True}],
    )

    devices_response = client.get("/api/v1/ss/mobile-sync/devices")
    assert devices_response.status_code == 200
    devices_payload = devices_response.json()
    assert devices_payload["status"] == "ok"
    assert devices_payload["total"] == 1

    review_response = client.get("/api/v1/ss/mobile-review/items")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert review_payload["total"] == 1
    assert review_payload["items"][0]["approval_status"] == "PENDING"


def test_mobile_review_transition_http_approve_delete_handoff(slide_scanner_http_context, monkeypatch, tmp_path: Path):
    client, db = slide_scanner_http_context
    image_path = tmp_path / "handoff.jpg"
    image_path.write_bytes(b"handoff")
    item_id = _insert_mobile_item(db, pc_inbox_path=str(image_path))

    def _fake_delete(*, db, item_id: int, adb_path, allowed_roots):
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
        return {"status": "done", "item_id": item_id, "results": {"/sdcard/DCIM/Camera/http-case.jpg": True}}

    monkeypatch.setattr(mobile_review_module, "process_remote_delete_for_item", _fake_delete)
    monkeypatch.setattr(
        mobile_review_module,
        "handoff_item_to_slides",
        lambda _db, _item_id: _mark_handoff_done(_db, _item_id, 501),
    )

    approve_response = client.post(f"/api/v1/ss/mobile-review/{item_id}/approve")
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["approval_status"] == "APPROVED"
    assert approve_payload["remote_delete_status"] == "PENDING"
    assert approve_payload["can_remote_delete"] is True

    delete_response = client.post(f"/api/v1/ss/mobile-review/{item_id}/remote-delete")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["status"] == "done"
    assert delete_payload["remote_delete_status"] == "DONE"
    assert delete_payload["can_handoff"] is True

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert handoff_response.status_code == 200
    payload = handoff_response.json()
    assert payload["slide_id"] == 501
    assert payload["slide_url"] == "/api/v1/ss/slides/501"
    assert payload["handoff_status"] == "DONE"
    assert payload["can_open_editor"] is True


def test_mobile_sync_devices_http_E_adb_unavailable_degraded(slide_scanner_http_context, monkeypatch):
    client, _db = slide_scanner_http_context

    def _raise(_adb_path):
        raise FileNotFoundError("adb not found")

    monkeypatch.setattr(mobile_sync_module, "list_connected_devices", _raise)
    response = client.get("/api/v1/ss/mobile-sync/devices")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert "adb not found" in (payload["error"] or "")


def test_mobile_review_handoff_http_409_when_delete_not_done(slide_scanner_http_context, tmp_path: Path):
    client, db = slide_scanner_http_context
    image_path = tmp_path / "blocked.jpg"
    image_path.write_bytes(b"blocked")
    item_id = _insert_mobile_item(
        db,
        pc_inbox_path=str(image_path),
        approval_status="APPROVED",
        remote_delete_status="PENDING",
    )

    response = client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert response.status_code == 409
    assert "remote_delete_status=DONE" in response.json()["detail"]


def test_mobile_review_items_http_approve_keeps_item_for_next_stage(slide_scanner_http_context, tmp_path: Path):
    client, db = slide_scanner_http_context
    image_path = tmp_path / "approve-keep.jpg"
    image_path.write_bytes(b"keep")
    item_id = _insert_mobile_item(db, pc_inbox_path=str(image_path), approval_status="PENDING")

    approve_response = client.post(f"/api/v1/ss/mobile-review/{item_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["approval_status"] == "APPROVED"

    list_response = client.get("/api/v1/ss/mobile-review/items")
    assert list_response.status_code == 200
    payload = list_response.json()
    by_id = {item["id"]: item for item in payload["items"]}
    assert item_id in by_id
    item = by_id[item_id]
    assert item["can_remote_delete"] is True
    assert item["can_handoff"] is False


def test_mobile_review_handoff_http_slide_lookup_by_response_slide_id(
    slide_scanner_http_context,
    monkeypatch,
    tmp_path: Path,
):
    client, db = slide_scanner_http_context
    image_path = tmp_path / "slide-lookup.jpg"
    image_path.write_bytes(b"lookup")
    item_id = _insert_mobile_item(
        db,
        pc_inbox_path=str(image_path),
        approval_status="APPROVED",
        remote_delete_status="DONE",
    )

    def _fake_handoff(_db, target_item_id: int) -> int:
        _db.execute(
            text(
                """
                INSERT INTO slides (
                    file_name,
                    file_path,
                    status,
                    captured_at,
                    source_app,
                    source_device_id,
                    thumbnail,
                    is_archived
                ) VALUES (
                    'slide-lookup.jpg',
                    :file_path,
                    'PENDING',
                    '2026-04-03T12:00:00+00:00',
                    'mobile:phone-a',
                    'phone-a',
                    :thumbnail,
                    0
                )
                """
            ),
            {
                "file_path": str(image_path),
                "thumbnail": b"thumbnail-bytes",
            },
        )
        slide_id = int(_db.execute(text("SELECT last_insert_rowid()")).scalar_one())
        _db.execute(
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
                "slide_id": slide_id,
                "item_id": target_item_id,
            },
        )
        _db.commit()
        return slide_id

    monkeypatch.setattr(mobile_review_module, "handoff_item_to_slides", _fake_handoff)

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{item_id}/handoff")
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    slide_id = handoff_payload["slide_id"]

    slide_response = client.get(f"/api/v1/ss/slides/{slide_id}")
    assert slide_response.status_code == 200
    slide_payload = slide_response.json()
    assert slide_payload["id"] == slide_id
