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
    PlanRecordRelation,
    PlanRecordRepoRef,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.routes import plan_records as route_module
from app.modules.dev_runner.routes.plan_records import router


def _make_client(monkeypatch):
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
        filename_hash="hash-cross-api",
        file_path="docs/archive/2026-05-05-cross.md",
        title="Cross repo API",
        status="archived",
    )
    db.add(record)
    db.commit()
    record_id = record.id
    db.close()

    class FakeWriter:
        def __init__(self, db):
            self.db = db

        def index_record(self, record_id, *, max_commits=30, dry_run=True):
            return {
                "dry_run": dry_run,
                "record_id": record_id,
                "repos": 2,
                "indexed": max_commits,
                "failed": 0,
                "skipped": 0,
                "errors": [],
            }

    monkeypatch.setattr(route_module, "PlanArchiveCrossRepoIndexWriter", FakeWriter)

    app = FastAPI()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    return TestClient(app), engine, record_id


def test_cross_repo_index_http_contract_right(monkeypatch):
    client, engine, record_id = _make_client(monkeypatch)
    try:
        dry_run = client.post(
            "/api/v1/plans/retrieval/cross-repo/index",
            json={"record_id": record_id, "max_commits": 7},
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["dry_run"] is True
        assert dry_run.json()["indexed"] == 7

        apply = client.post(
            "/api/v1/plans/retrieval/cross-repo/index",
            json={"record_id": record_id, "max_commits": 3, "apply": True},
        )
        assert apply.status_code == 200
        assert apply.json()["dry_run"] is False
        assert apply.json()["record_id"] == record_id
    finally:
        engine.dispose()
