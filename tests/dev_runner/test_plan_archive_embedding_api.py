from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordChunkEmbedding,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.routes.plan_records import router


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordChunkEmbedding.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    record = PlanRecord(
        filename_hash="hash-api-embedding",
        file_path="docs/archive/2026-01-01-api-embedding.md",
        title="API embedding",
        archived_at=datetime.now(),
        status="archived",
    )
    db.add(record)
    db.flush()
    db.add(
        PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="body",
            text="embedding endpoint dry run",
            content_hash="hash-api-embedding-chunk",
            token_estimate=4,
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


def test_post_embeddings_index_right_returns_dry_run_shape():
    client, engine = _make_client()
    try:
        response = client.post("/api/v1/plans/retrieval/embeddings/index", json={"limit": 5})
        assert response.status_code == 200
        body = response.json()
        assert body["dry_run"] is True
        assert body["indexed"] == 1
        assert body["provider"] == "local-hash"
        assert body["model"] == "hash-bow-v1"
    finally:
        engine.dispose()


def test_post_embeddings_index_error_invalid_provider_returns_400():
    client, engine = _make_client()
    try:
        response = client.post(
            "/api/v1/plans/retrieval/embeddings/index",
            json={"limit": 5, "provider": "unknown-provider"},
        )
        assert response.status_code == 400
        assert "Unsupported plan archive embedding provider" in response.json()["detail"]
    finally:
        engine.dispose()
