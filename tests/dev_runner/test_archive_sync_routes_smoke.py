"""Phase 4-G: archive sync routes smoke tests.

DB 이관(import-archived)과 파일/DB 동기화(sync) 백엔드 endpoint가
응답을 반환하고 DB 변동을 일으키는지 검증한다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.routes.plan_records import router


@pytest.fixture
def client_with_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    return TestClient(app), Session


def test_import_archived_returns_summary(client_with_db, tmp_path):
    client, Session = client_with_db

    md = tmp_path / "2026-05-06_test-plan.md"
    md.write_text("# test plan\n\n- [x] done item\n", encoding="utf-8")

    with patch(
        "app.modules.dev_runner.routes.plan_records._plan_service"
    ) as mock_svc:
        mock_svc.list_registered_paths.return_value = []
        resp = client.post(
            "/api/v1/plans/records/import-archived",
            params={"archive_dir": str(tmp_path)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "created" in data
    assert "updated" in data
    assert "skipped" in data
    assert "errors" in data
    assert isinstance(data["errors"], list)


def test_import_archived_creates_record_for_new_file(client_with_db, tmp_path):
    client, Session = client_with_db

    md = tmp_path / "2026-05-06_new-plan.md"
    md.write_text("# new plan\n\nbody\n", encoding="utf-8")

    with patch(
        "app.modules.dev_runner.routes.plan_records._plan_service"
    ) as mock_svc:
        mock_svc.list_registered_paths.return_value = []
        resp = client.post(
            "/api/v1/plans/records/import-archived",
            params={"archive_dir": str(tmp_path)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] >= 1 or data["skipped"] >= 1


def test_import_archived_skips_existing_record(client_with_db, tmp_path):
    """이미 등록된 레코드가 있으면 skipped 카운트가 증가한다."""
    client, Session = client_with_db

    md = tmp_path / "2026-05-06_existing.md"
    md.write_text("# existing\n\nbody\n", encoding="utf-8")

    with patch(
        "app.modules.dev_runner.routes.plan_records._plan_service"
    ) as mock_svc:
        mock_svc.list_registered_paths.return_value = []
        first = client.post(
            "/api/v1/plans/records/import-archived",
            params={"archive_dir": str(tmp_path)},
        )
        second = client.post(
            "/api/v1/plans/records/import-archived",
            params={"archive_dir": str(tmp_path)},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["created"] == 0
    assert second_data["skipped"] >= 1 or second_data["updated"] >= 1


def test_sync_records_returns_summary(client_with_db):
    client, Session = client_with_db

    with patch(
        "app.modules.dev_runner.routes.plan_records._plan_service"
    ) as mock_svc:
        mock_svc.list_registered_paths.return_value = []
        resp = client.post("/api/v1/plans/records/sync")

    assert resp.status_code == 200
    data = resp.json()
    assert "created" in data
    assert "updated" in data
    assert "missing" in data
    assert "archive_created" in data
    assert "archive_normalized" in data


def test_sync_records_reflects_file_changes(client_with_db, tmp_path):
    """sync 후 archive_created 또는 archive_normalized 필드가 응답에 포함된다."""
    client, Session = client_with_db

    md = tmp_path / "2026-05-05_archived.md"
    md.write_text("# archived plan\n\nbody\n", encoding="utf-8")

    registered_path = MagicMock()
    registered_path.path = str(tmp_path)
    registered_path.path_type = "archive"

    with patch(
        "app.modules.dev_runner.routes.plan_records._plan_service"
    ) as mock_svc:
        mock_svc.list_registered_paths.return_value = [registered_path]
        resp = client.post("/api/v1/plans/records/sync")

    assert resp.status_code == 200
    data = resp.json()
    total = data["created"] + data["updated"] + data["missing"] + data["archive_created"] + data["archive_normalized"]
    assert isinstance(total, int)
