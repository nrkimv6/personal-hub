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
    PlanRecordFileRef,
    PlanRecordRepoRef,
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
        PlanRecordFileRef.__table__,
        PlanRecordRepoRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    record = PlanRecord(
        filename_hash="hash-api",
        file_path="docs/archive/2026-01-01-api.md",
        title="API retrieval",
        category="infra",
        archived_at=datetime.now(),
        raw_content="# API retrieval\n\n- [ ] `app/models/plan_record.py`: update",
        status="archived",
    )
    db.add(record)
    db.flush()
    db.add(
        PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="todo",
            heading="TODO",
            text="API retrieval evidence app/models/plan_record.py",
            content_hash="h",
            token_estimate=5,
        )
    )
    db.add(
        PlanRecordFileRef(
            plan_record_id=record.id,
            source_type="mentioned_in_plan",
            path="app/models/plan_record.py",
            module="app/models",
        )
    )
    db.commit()

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


def test_search_context_metrics_http_contract_right():
    client, engine = _make_client()
    try:
        search = client.post("/api/v1/plans/retrieval/search", json={"q": "retrieval", "limit": 5})
        assert search.status_code == 200
        assert search.json()["total"] == 1

        context = client.post("/api/v1/plans/retrieval/context", json={"q": "retrieval", "token_budget": 500})
        assert context.status_code == 200
        assert context.json()["evidence"]

        metrics = client.post("/api/v1/plans/retrieval/metrics", json={"category": "infra"})
        assert metrics.status_code == 200
        assert metrics.json()["total_plans"] == 1
    finally:
        engine.dispose()
