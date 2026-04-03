from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.routers import mobile_review_router, mobile_sync_router, slides_router
from app.modules.slide_scanner.routers import mobile_review as mobile_review_module


def _apply_sql_file(engine, sql_path: Path) -> None:
    sql_content = sql_path.read_text(encoding="utf-8")
    statements = [segment.strip() for segment in sql_content.split(";") if segment.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (96, 72), color=color)
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture()
def mobile_sync_e2e_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Session, Callable[[str, str, bytes], Path]]]:
    db_path = tmp_path / "slide_scanner_e2e.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    migrations_dir = Path(__file__).resolve().parents[2] / "app" / "modules" / "slide_scanner" / "migrations"
    _apply_sql_file(engine, migrations_dir / "001_initial.sql")
    _apply_sql_file(engine, migrations_dir / "010_mobile_ingest.sql")
    _apply_sql_file(engine, migrations_dir / "011_slides_source_device.sql")
    _apply_sql_file(engine, migrations_dir / "012_rectifier_detect_meta.sql")

    data_dir = tmp_path / "slide_scanner_data"
    originals_dir = data_dir / "originals"
    output_dir = data_dir / "output"
    inbox_dir = data_dir / "mobile_inbox"
    approved_dir = data_dir / "mobile_approved"
    rejected_dir = data_dir / "mobile_rejected"
    for directory in (data_dir, originals_dir, output_dir, inbox_dir, approved_dir, rejected_dir):
        directory.mkdir(parents=True, exist_ok=True)

    fake_adb_root = data_dir / "fake_adb_devices"
    fake_adb_root.mkdir(parents=True, exist_ok=True)
    fake_adb_script = Path(__file__).resolve().parents[1] / "modules" / "slide_scanner" / "fixtures" / "fake_adb.py"

    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings, "ORIGINALS_DIR", originals_dir)
    monkeypatch.setattr(settings, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(settings, "MOBILE_INBOX_DIR", inbox_dir)
    monkeypatch.setattr(settings, "MOBILE_APPROVED_DIR", approved_dir)
    monkeypatch.setattr(settings, "MOBILE_REJECTED_DIR", rejected_dir)
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_script)
    monkeypatch.setenv("FAKE_ADB_ROOT", str(fake_adb_root))
    monkeypatch.setenv("FAKE_ADB_SERIALS", "FAKE001,FAKE002")

    def _add_remote_file(serial: str, remote_path: str, content: bytes) -> Path:
        normalized = remote_path.replace("\\", "/").lstrip("/")
        target = fake_adb_root / serial / Path(*[part for part in normalized.split("/") if part])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

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
        yield client, session, _add_remote_file

    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_mobile_sync_e2e_two_devices_to_handoff(
    mobile_sync_e2e_context: tuple[TestClient, Session, Callable[[str, str, bytes], Path]],
):
    client, _db, add_remote_file = mobile_sync_e2e_context

    remote_path = "/sdcard/DCIM/Camera/IMG_E2E_SHARED.jpg"
    add_remote_file("FAKE001", remote_path, _jpeg_bytes((120, 40, 40)))
    add_remote_file("FAKE002", remote_path, _jpeg_bytes((40, 120, 40)))

    run_response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "ok"
    assert run_payload["pulled"] == 2
    assert run_payload["inserted"] == 2

    queue_response = client.get("/api/v1/ss/mobile-review/items")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["total"] == 2
    serials = {item["device_serial"] for item in queue_payload["items"]}
    assert serials == {"FAKE001", "FAKE002"}

    target_item_id = queue_payload["items"][0]["id"]
    approve_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/approve")
    assert approve_response.status_code == 200

    remote_delete_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/remote-delete")
    assert remote_delete_response.status_code == 200
    assert remote_delete_response.json()["status"] == "done"

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/handoff")
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    assert handoff_payload["slide_id"] > 0
    assert handoff_payload["slide_url"].startswith("/api/v1/ss/slides/")


def test_mobile_sync_e2e_rejected_item_not_handed_off(
    mobile_sync_e2e_context: tuple[TestClient, Session, Callable[[str, str, bytes], Path]],
):
    client, _db, add_remote_file = mobile_sync_e2e_context

    remote_path = "/sdcard/DCIM/Camera/IMG_E2E_REJECT.jpg"
    add_remote_file("FAKE001", remote_path, _jpeg_bytes((30, 30, 180)))

    run_response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert run_response.status_code == 200
    assert run_response.json()["inserted"] == 1

    queue_response = client.get("/api/v1/ss/mobile-review/items")
    assert queue_response.status_code == 200
    target_item_id = queue_response.json()["items"][0]["id"]

    reject_response = client.post(
        f"/api/v1/ss/mobile-review/{target_item_id}/reject",
        json={"reason": "blurred"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["approval_status"] == "REJECTED"

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/handoff")
    assert handoff_response.status_code == 409


def test_mobile_sync_e2e_can_open_editor_after_handoff(
    mobile_sync_e2e_context: tuple[TestClient, Session, Callable[[str, str, bytes], Path]],
):
    client, _db, add_remote_file = mobile_sync_e2e_context

    remote_path = "/sdcard/DCIM/Camera/IMG_E2E_EDITOR_OPEN.jpg"
    add_remote_file("FAKE001", remote_path, _jpeg_bytes((80, 160, 220)))

    run_response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert run_response.status_code == 200
    assert run_response.json()["inserted"] == 1

    queue_response = client.get("/api/v1/ss/mobile-review/items")
    assert queue_response.status_code == 200
    item = queue_response.json()["items"][0]
    target_item_id = item["id"]
    assert item["can_open_editor"] is False

    approve_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/approve")
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["approval_status"] == "APPROVED"
    assert approve_payload["can_open_editor"] is False

    delete_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/remote-delete")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "done"

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/handoff")
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    assert handoff_payload["handoff_status"] == "DONE"
    assert handoff_payload["can_open_editor"] is True


def test_mobile_sync_e2e_remote_delete_retry_then_handoff(
    mobile_sync_e2e_context: tuple[TestClient, Session, Callable[[str, str, bytes], Path]],
    monkeypatch: pytest.MonkeyPatch,
):
    client, _db, add_remote_file = mobile_sync_e2e_context

    remote_path = "/sdcard/DCIM/Camera/IMG_E2E_RETRY.jpg"
    add_remote_file("FAKE001", remote_path, _jpeg_bytes((210, 90, 90)))

    run_response = client.post("/api/v1/ss/mobile-sync/run", json={"background": False})
    assert run_response.status_code == 200
    assert run_response.json()["inserted"] == 1

    queue_response = client.get("/api/v1/ss/mobile-review/items")
    assert queue_response.status_code == 200
    target_item_id = queue_response.json()["items"][0]["id"]

    approve_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["approval_status"] == "APPROVED"

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
        return {"status": "done", "item_id": item_id, "results": {remote_path: True}}

    monkeypatch.setattr(mobile_review_module, "process_remote_delete_for_item", _toggle_remote_delete)

    first_delete = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/remote-delete")
    assert first_delete.status_code == 200
    first_payload = first_delete.json()
    assert first_payload["status"] == "failed"
    assert first_payload["remote_delete_status"] == "FAILED"
    assert first_payload["can_handoff"] is False

    retry_delete = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/remote-delete/retry")
    assert retry_delete.status_code == 200
    retry_payload = retry_delete.json()
    assert retry_payload["status"] == "done"
    assert retry_payload["remote_delete_status"] == "DONE"
    assert retry_payload["can_handoff"] is True

    handoff_response = client.post(f"/api/v1/ss/mobile-review/{target_item_id}/handoff")
    assert handoff_response.status_code == 200
    handoff_payload = handoff_response.json()
    assert handoff_payload["handoff_status"] == "DONE"
    assert handoff_payload["can_open_editor"] is True
