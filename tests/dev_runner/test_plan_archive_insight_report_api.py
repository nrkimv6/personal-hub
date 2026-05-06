from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef
from app.modules.dev_runner.routes.plan_records import router


def _make_client(with_report=True):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordFileRef.__table__,
        PlanArchiveInsightReport.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    db = Session()
    if with_report:
        record = PlanRecord(
            filename_hash="hash",
            file_path="docs/archive/a.md",
            archived_at=datetime(2026, 1, 1),
            status="archived",
            category="infra",
        )
        db.add(record)
        db.flush()
        chunk = PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="body",
            text="evidence",
            content_hash="h",
            token_estimate=1,
        )
        db.add(chunk)
        db.flush()
        db.add(PlanRecordFileRef(plan_record_id=record.id, source_type="git_changed", path="app/a.py", module="app"))
        report = PlanArchiveInsightReport(
            grouping="category",
            metrics_hash="hash",
            metrics_json={"total_plans": 1},
            evidence_json=[{"record_id": record.id, "chunk_id": chunk.id, "text": "evidence"}],
            insight_json={"summary": "summary", "root_causes": ["root"], "recommendations": ["rec"]},
            provider="claude",
            model="sonnet",
            status="completed",
        )
        db.add(report)
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


def test_list_reports_right():
    client, engine = _make_client()
    try:
        response = client.get("/api/v1/plans/insights/reports")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["summary"] == "summary"
    finally:
        engine.dispose()


def test_list_reports_boundary_empty_returns_empty_page():
    client, engine = _make_client(with_report=False)
    try:
        response = client.get("/api/v1/plans/insights/reports")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}
    finally:
        engine.dispose()


def test_get_report_detail_includes_evidence_right():
    client, engine = _make_client()
    try:
        response = client.get("/api/v1/plans/insights/reports/1")
        assert response.status_code == 200
        body = response.json()
        assert body["metrics"]["total_plans"] == 1
        assert body["evidence"][0]["text"] == "evidence"
    finally:
        engine.dispose()


def test_get_report_detail_error_missing_report_returns_404():
    client, engine = _make_client(with_report=False)
    try:
        response = client.get("/api/v1/plans/insights/reports/404")
        assert response.status_code == 404
    finally:
        engine.dispose()
