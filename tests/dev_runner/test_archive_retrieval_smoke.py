"""Phase 4-G: archive retrieval smoke tests.

archive retrieval/search/metrics endpoint가 응답하고
cross-repo index dry-run이 동작하는지 검증한다.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
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


def _make_app_with_record():
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
        filename_hash="hash-retrieval-smoke",
        file_path="docs/archive/2026-05-06-retrieval-smoke.md",
        title="Retrieval smoke test plan",
        category="infra",
        archived_at=datetime.now(),
        raw_content="# Retrieval smoke\n\n- [x] app/models/plan_record.py update",
        status="archived",
        llm_processed_at=datetime.now(),
    )
    db.add(record)
    db.flush()
    db.add(
        PlanRecordChunk(
            plan_record_id=record.id,
            chunk_index=0,
            section_type="todo",
            heading="TODO",
            text="retrieval smoke test app/models/plan_record.py",
            content_hash="h-smoke",
            token_estimate=8,
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
    return TestClient(app), engine, record.id


def test_retrieval_search_returns_results():
    client, engine, _ = _make_app_with_record()
    try:
        resp = client.post("/api/v1/plans/retrieval/search", json={"q": "retrieval smoke", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "results" in data
        assert data["total"] >= 1
    finally:
        engine.dispose()


def test_retrieval_search_empty_query_returns_all():
    client, engine, _ = _make_app_with_record()
    try:
        resp = client.post("/api/v1/plans/retrieval/search", json={"limit": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
    finally:
        engine.dispose()


def test_retrieval_metrics_returns_plan_counts():
    client, engine, _ = _make_app_with_record()
    try:
        resp = client.post("/api/v1/plans/retrieval/metrics", json={"category": "infra"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_plans" in data
        assert data["total_plans"] >= 1
    finally:
        engine.dispose()


def test_retrieval_metrics_empty_category_returns_totals():
    client, engine, _ = _make_app_with_record()
    try:
        resp = client.post("/api/v1/plans/retrieval/metrics", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_plans" in data
    finally:
        engine.dispose()


def test_cross_repo_index_dry_run_returns_result():
    """cross-repo index dry-run은 apply=False 시 DB를 수정하지 않고 결과를 반환한다."""
    client, engine, record_id = _make_app_with_record()
    try:
        with patch(
            "app.modules.dev_runner.routes.plan_records.PlanArchiveCrossRepoIndexWriter"
        ) as MockWriter:
            mock_instance = MagicMock()
            MockWriter.return_value = mock_instance
            mock_instance.index_record.return_value = {
                "record_id": record_id,
                "dry_run": True,
                "indexed": 0,
                "failed": 0,
                "errors": [],
            }
            resp = client.post(
                "/api/v1/plans/retrieval/cross-repo/index",
                json={"record_id": record_id, "apply": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert "indexed" in data
        mock_instance.index_record.assert_called_once()
    finally:
        engine.dispose()


def test_archive_index_dry_run_returns_result():
    """archive index dry-run(apply=False)은 200을 반환한다."""
    client, engine, _ = _make_app_with_record()
    try:
        with patch(
            "app.modules.dev_runner.routes.plan_records.PlanArchiveIndexService"
        ) as MockIndex:
            mock_instance = MagicMock()
            MockIndex.return_value = mock_instance
            mock_instance.index_archived_records.return_value = {
                "dry_run": True,
                "indexed": 0,
                "failed": 0,
                "skipped": 1,
                "errors": [],
            }
            resp = client.post(
                "/api/v1/plans/records/index",
                json={"limit": 10, "force": False, "apply": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "indexed" in data
        assert "skipped" in data
    finally:
        engine.dispose()
