from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.routers import slides as slides_router_module
from app.modules.slide_scanner.routers import slides_router


def _apply_sql_file(engine, sql_path: Path) -> None:
    sql_content = sql_path.read_text(encoding="utf-8")
    statements = [segment.strip() for segment in sql_content.split(";") if segment.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _apply_slide_migrations(engine, migrations_dir: Path) -> None:
    for migration_name in [
        "001_initial.sql",
        "002_settings.sql",
        "003_aspect_ratio.sql",
        "004_filters.sql",
        "005_ocr.sql",
        "006_tags.sql",
        "010_mobile_ingest.sql",
        "011_slides_source_device.sql",
        "012_rectifier_detect_meta.sql",
    ]:
        _apply_sql_file(engine, migrations_dir / migration_name)


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (128, 96), color=(240, 240, 240))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _prepare_dirs(base: Path) -> None:
    data_dir = base / "slide_scanner_data"
    originals_dir = data_dir / "originals"
    output_dir = data_dir / "output"
    archive_dir = data_dir / "archive"
    inbox_dir = data_dir / "mobile_inbox"
    approved_dir = data_dir / "mobile_approved"
    rejected_dir = data_dir / "mobile_rejected"

    for directory in (
        data_dir,
        originals_dir,
        output_dir,
        archive_dir,
        inbox_dir,
        approved_dir,
        rejected_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    settings.DATA_DIR = data_dir
    settings.ORIGINALS_DIR = originals_dir
    settings.OUTPUT_DIR = output_dir
    settings.ARCHIVE_DIR = archive_dir
    settings.MOBILE_INBOX_DIR = inbox_dir
    settings.MOBILE_APPROVED_DIR = approved_dir
    settings.MOBILE_REJECTED_DIR = rejected_dir


@pytest.fixture()
def slide_scanner_detect_meta_http_context(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, Session]]:
    original_dirs = {
        "DATA_DIR": settings.DATA_DIR,
        "ORIGINALS_DIR": settings.ORIGINALS_DIR,
        "OUTPUT_DIR": settings.OUTPUT_DIR,
        "ARCHIVE_DIR": settings.ARCHIVE_DIR,
        "MOBILE_INBOX_DIR": settings.MOBILE_INBOX_DIR,
        "MOBILE_APPROVED_DIR": settings.MOBILE_APPROVED_DIR,
        "MOBILE_REJECTED_DIR": settings.MOBILE_REJECTED_DIR,
    }

    db_path = tmp_path / "slide_scanner_http_detect_meta.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    migrations_dir = Path(__file__).resolve().parents[1] / "app" / "modules" / "slide_scanner" / "migrations"
    _apply_slide_migrations(engine, migrations_dir)
    _prepare_dirs(tmp_path)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    app = FastAPI()
    app.include_router(slides_router, prefix="/api/v1/ss")

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        for key, value in original_dirs.items():
            setattr(settings, key, value)


def test_slide_upload_http_returns_detect_meta(
    slide_scanner_detect_meta_http_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _session = slide_scanner_detect_meta_http_context
    monkeypatch.setattr(
        slides_router_module.rectifier_client,
        "detect_with_meta",
        lambda _path: {
            "points": [(1.0, 1.0), (127.0, 1.0), (127.0, 95.0), (1.0, 95.0)],
            "meta": {
                "requested_engine": "dl",
                "selected_engine": "opencv",
                "confidence": 0.72,
                "fallback_reason": "model_missing",
                "selection_reason": "opencv_higher",
            },
        },
    )

    response = client.post(
        "/api/v1/ss/slides/upload",
        files={"file": ("http-meta.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["detect_meta"]["selected_engine"] == "opencv"
    assert payload["detect_meta"]["fallback_reason"] == "model_missing"


def test_slide_get_http_returns_nullable_detect_meta(
    slide_scanner_detect_meta_http_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _session = slide_scanner_detect_meta_http_context
    monkeypatch.setattr(
        slides_router_module.rectifier_client,
        "detect_with_meta",
        lambda _path: {
            "points": [(2.0, 2.0), (126.0, 2.0), (126.0, 94.0), (2.0, 94.0)],
            "meta": {
                "requested_engine": "dl",
                "selected_engine": "dl",
                "confidence": 0.93,
                "fallback_reason": None,
                "selection_reason": "dl_higher",
            },
        },
    )

    upload = client.post(
        "/api/v1/ss/slides/upload",
        files={"file": ("http-meta-get.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert upload.status_code == 200
    slide_id = upload.json()["id"]

    response = client.get(f"/api/v1/ss/slides/{slide_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["detect_meta"]["selected_engine"] == "dl"
    assert payload["detect_meta"]["confidence"] == 0.93
    assert payload["detect_meta"]["fallback_reason"] is None
