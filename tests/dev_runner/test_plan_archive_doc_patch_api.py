import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import PROJECT_ROOT
from app.database import get_db
from app.models.plan_archive_doc_patch import PlanArchiveDocPatchProposal
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.routes.plan_records import router


def _make_client(with_record=True):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanArchiveDocPatchProposal.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    if with_record:
        archive_path = PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "archive" / "api.md"
        db.add(
            PlanRecord(
                filename_hash="hash-api",
                file_path=str(archive_path),
                status="archived",
                raw_content="old",
            )
        )
        db.commit()
    db.close()

    app = FastAPI()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    return TestClient(app), engine


def test_preview_http_contract_right():
    client, engine = _make_client()
    try:
        response = client.post(
            "/api/v1/plans/doc-patches/preview",
            json={"record_id": 1, "patch_text": json.dumps({"replacements": [{"old": "old", "new": "new"}]})},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "previewed"
        assert body["preview_text"] == "new"
    finally:
        engine.dispose()


def test_preview_http_error_unknown_source_returns_404():
    client, engine = _make_client(with_record=False)
    try:
        response = client.post("/api/v1/plans/doc-patches/preview", json={"record_id": 404, "patch_text": ""})
        assert response.status_code == 404
    finally:
        engine.dispose()


def test_apply_requires_confirm_right():
    client, engine = _make_client()
    try:
        client.post("/api/v1/plans/doc-patches/preview", json={"record_id": 1, "patch_text": ""})
        response = client.post("/api/v1/plans/doc-patches/1/apply", json={"confirm": False})
        assert response.status_code == 400
        assert response.json()["detail"] == "CONFIRM_REQUIRED"
    finally:
        engine.dispose()


def test_apply_http_error_outside_archive_path_returns_400():
    client, engine = _make_client()
    try:
        response = client.post(
            "/api/v1/plans/doc-patches/preview",
            json={"record_id": 1, "target_path": str(PROJECT_ROOT / "outside.md"), "patch_text": ""},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "TARGET_OUTSIDE_ARCHIVE"
    finally:
        engine.dispose()
