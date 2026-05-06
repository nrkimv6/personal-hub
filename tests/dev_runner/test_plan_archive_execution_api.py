from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.routes.plan_records import (
    list_archive_execution_history,
    run_archive_executions,
    sync_archive_executions,
)
from app.modules.dev_runner.schemas import PlanArchiveExecutionRunRequest, PlanArchiveSelectedProfile


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def test_run_archive_executions_queues_selected_record(db):
    record = PlanRecord(
        filename_hash="hash-api",
        file_path="/archive/2026-05-06_api.md",
        raw_content="# api",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = run_archive_executions(
            PlanArchiveExecutionRunRequest(
                record_ids=[record.id],
                selected_profiles=[PlanArchiveSelectedProfile(engine="claude", profile_name="work")],
            ),
            db=db,
        )

    assert result["queued"] == 1
    assert result["profile_count"] == 1
    assert len(result["request_ids"]) == 1


def test_run_archive_executions_preserves_selected_target_model_in_request(db):
    record = PlanRecord(
        filename_hash="hash-api-selected-target",
        file_path="/archive/2026-05-06_api-selected-target.md",
        raw_content="# api selected target",
        archived_at=datetime(2026, 5, 6),
        llm_processed_at=None,
    )
    db.add(record)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.side_effect = lambda caller_type, provider, model: (
        provider or "claude",
        model or "fallback-model",
    )

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = run_archive_executions(
            PlanArchiveExecutionRunRequest(
                record_ids=[record.id],
                selected_targets=[
                    {
                        "provider": "claude",
                        "model": "claude-sonnet-4-5",
                        "profile_key": "claude:work",
                        "engine": "claude",
                        "profile_name": "work",
                        "label": "claude/work/claude-sonnet-4-5",
                    }
                ],
            ),
            db=db,
        )

    request = db.query(LLMRequest).filter_by(id=result["request_ids"][0]).one()
    assert request.provider == "claude"
    assert request.model == "claude-sonnet-4-5"
    assert request.dedupe_key == "profile:claude:work:claude-sonnet-4-5"


def test_sync_and_history_endpoints_return_wrapper_shape(db):
    sync_result = sync_archive_executions(db=db)
    history = list_archive_execution_history(limit=10, db=db)

    assert sync_result["checked"] == 0
    assert history["items"] == []
    assert history["total"] == 0
    assert history["limit"] == 10


# ===== Reanalyze HTTP-level tests =====

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(test_db_engine):
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_archived_record(session, path: str):
    from datetime import datetime
    from app.modules.dev_runner.services.plan_record_service import PlanRecordService, _compute_filename_hash
    svc = PlanRecordService(session)
    record = svc.get_or_create(path)
    record.status = "archived"
    record.archived_at = datetime.now()
    session.flush()
    session.commit()
    return record


# ===== POST /api/v1/plans/records/{id}/reanalyze =====

class TestReanalyzeEndpoint:

    def test_reanalyze_codex_no_profile(self, client, test_db_session):
        """profile_key 없이 Codex provider로 재분석 요청 큐잉 → 200 + queued=True"""
        record = _make_archived_record(test_db_session, "/archive/2026-05-06-codex-test.md")
        payload = {"provider": "codex", "model": "", "profile_key": None}

        resp = client.post(f"/api/v1/plans/records/{record.id}/reanalyze", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] is True
        assert data["provider"] == "codex"
        assert "request_id" in data

    def test_reanalyze_duplicate_returns_existing(self, client, test_db_session):
        """이미 pending 요청이 있으면 queued=False, 기존 request_id 반환"""
        record = _make_archived_record(test_db_session, "/archive/2026-05-06-codex-dup.md")
        payload = {"provider": "claude", "model": "", "profile_key": None}

        # 첫 요청
        resp1 = client.post(f"/api/v1/plans/records/{record.id}/reanalyze", json=payload)
        assert resp1.status_code == 200
        assert resp1.json()["queued"] is True
        first_id = resp1.json()["request_id"]

        # 중복 요청 → queued=False, 동일 id
        resp2 = client.post(f"/api/v1/plans/records/{record.id}/reanalyze", json=payload)
        assert resp2.status_code == 200
        assert resp2.json()["queued"] is False
        assert resp2.json()["request_id"] == first_id

    def test_reanalyze_unsupported_provider_returns_400(self, client, test_db_session):
        """지원하지 않는 provider → 400 에러"""
        record = _make_archived_record(test_db_session, "/archive/2026-05-06-bad-provider.md")
        payload = {"provider": "unknown-xyz", "model": "", "profile_key": None}

        resp = client.post(f"/api/v1/plans/records/{record.id}/reanalyze", json=payload)
        assert resp.status_code == 400
        assert "unsupported provider" in resp.json()["detail"].lower()

    def test_reanalyze_nonexistent_record_returns_404(self, client):
        """존재하지 않는 record_id → 404"""
        payload = {"provider": "claude", "model": ""}
        resp = client.post("/api/v1/plans/records/99999999/reanalyze", json=payload)
        assert resp.status_code == 404

    def test_reanalyze_claude_provider_queued(self, client, test_db_session):
        """claude provider로 큐잉 → 200 + provider=claude"""
        record = _make_archived_record(test_db_session, "/archive/2026-05-06-claude-test.md")
        payload = {"provider": "claude", "model": "claude-opus-4-7", "profile_key": None}

        resp = client.post(f"/api/v1/plans/records/{record.id}/reanalyze", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] is True
        assert data["provider"] == "claude"
