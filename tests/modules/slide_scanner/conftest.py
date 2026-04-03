from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.modules.slide_scanner.config import settings
from app.modules.slide_scanner.database import get_db
from app.modules.slide_scanner.routers import (
    gallery_router,
    health_router,
    mobile_review_router,
    mobile_sync_router,
    slides_router,
)


def _apply_sql_file(engine, sql_path: Path) -> None:
    sql_content = sql_path.read_text(encoding="utf-8")
    statements = [segment.strip() for segment in sql_content.split(";") if segment.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


@pytest.fixture()
def slide_scanner_session(tmp_path: Path):
    db_path = tmp_path / "slide_scanner_test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    migrations_dir = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "modules"
        / "slide_scanner"
        / "migrations"
    )
    _apply_sql_file(engine, migrations_dir / "001_initial.sql")
    _apply_sql_file(engine, migrations_dir / "002_settings.sql")
    _apply_sql_file(engine, migrations_dir / "003_aspect_ratio.sql")
    _apply_sql_file(engine, migrations_dir / "004_filters.sql")
    _apply_sql_file(engine, migrations_dir / "005_ocr.sql")
    _apply_sql_file(engine, migrations_dir / "006_tags.sql")
    _apply_sql_file(engine, migrations_dir / "010_mobile_ingest.sql")
    _apply_sql_file(engine, migrations_dir / "011_slides_source_device.sql")

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def slide_scanner_test_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    return {
        "data_dir": data_dir,
        "originals_dir": originals_dir,
        "output_dir": output_dir,
        "inbox_dir": inbox_dir,
        "approved_dir": approved_dir,
        "rejected_dir": rejected_dir,
    }


@pytest.fixture()
def fake_adb_path(
    monkeypatch: pytest.MonkeyPatch,
    slide_scanner_test_dirs: dict[str, Path],
) -> Path:
    fake_adb_script = (
        Path(__file__).resolve().parent / "fixtures" / "fake_adb.py"
    )
    fake_root = slide_scanner_test_dirs["data_dir"] / "fake_adb_devices"
    fake_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("FAKE_ADB_ROOT", str(fake_root))
    monkeypatch.setenv("FAKE_ADB_SERIALS", "FAKE001,FAKE002")
    monkeypatch.setattr(settings, "ADB_PATH", fake_adb_script)
    return fake_adb_script


@pytest.fixture()
def fake_adb_root(slide_scanner_test_dirs: dict[str, Path]) -> Path:
    root = slide_scanner_test_dirs["data_dir"] / "fake_adb_devices"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def fake_adb_add_remote_file(fake_adb_root: Path):
    def _add(serial: str, remote_path: str, content: bytes) -> Path:
        target = fake_adb_root / serial / Path(*[part for part in remote_path.lstrip("/").split("/") if part])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    return _add


@pytest.fixture()
def slide_scanner_app(slide_scanner_session, slide_scanner_test_dirs):
    app = FastAPI()
    app.include_router(health_router, prefix="/api/v1/ss")
    app.include_router(slides_router, prefix="/api/v1/ss")
    app.include_router(gallery_router, prefix="/api/v1/ss")
    app.include_router(mobile_sync_router, prefix="/api/v1/ss")
    app.include_router(mobile_review_router, prefix="/api/v1/ss")

    def override_get_db():
        yield slide_scanner_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def slide_scanner_client(slide_scanner_app: FastAPI):
    with TestClient(slide_scanner_app) as client:
        yield client
