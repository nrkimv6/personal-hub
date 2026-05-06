from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.plan_record import PlanRecord, PlanRecordRelation
from app.modules.dev_runner.routes.plan_records import router


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PlanRecord.__table__.create(bind=engine, checkfirst=True)
    PlanRecordRelation.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    source = PlanRecord(
        filename_hash="hash-source",
        file_path="docs/archive/2026-05-06_fix-source.md",
        title="Source",
        archived_at=datetime.now(),
        status="archived",
    )
    target = PlanRecord(
        filename_hash="hash-target",
        file_path="docs/archive/2026-05-06_fix-target.md",
        title="Target",
        archived_at=datetime.now(),
        status="archived",
    )
    db.add_all([source, target])
    db.flush()
    db.add(
        PlanRecordRelation(
            source_plan_record_id=source.id,
            target_plan_record_id=target.id,
            relation_type="unresolved_followup",
            score=95,
            evidence={"generated_by": "plan_body_relation_tracking", "line_number": 3},
        )
    )
    db.commit()
    source_id = source.id
    target_id = target.id
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
    return TestClient(app), engine, source_id, target_id


def test_record_relations_returns_outgoing_and_incoming():
    client, engine, source_id, target_id = _make_client()
    try:
        outgoing = client.get(f"/api/v1/plans/records/{source_id}/relations?direction=outgoing")
        assert outgoing.status_code == 200
        assert outgoing.json()[0]["relation_type"] == "unresolved_followup"
        assert outgoing.json()[0]["target"]["id"] == target_id

        incoming = client.get(f"/api/v1/plans/records/{target_id}/relations?direction=incoming")
        assert incoming.status_code == 200
        assert incoming.json()[0]["source"]["id"] == source_id
    finally:
        engine.dispose()


def test_relation_statistics_returns_unresolved_followup_cases():
    client, engine, source_id, _target_id = _make_client()
    try:
        response = client.get("/api/v1/plans/statistics/relations")
        assert response.status_code == 200
        data = response.json()
        assert data["relation_counts"]["unresolved_followup"] == 1
        assert data["unresolved_followup_count"] == 1
        assert data["recent_unresolved_followups"][0]["source"]["id"] == source_id
    finally:
        engine.dispose()


def test_record_relations_filters_relation_type():
    client, engine, source_id, _target_id = _make_client()
    try:
        response = client.get(f"/api/v1/plans/records/{source_id}/relations?relation_type=guard")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        engine.dispose()
