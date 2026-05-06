"""Plan Archive 실행 API HTTP 레벨 테스트

엔드포인트: POST /api/v1/plans/records/{id}/reanalyze
TestClient 사용, test_db_session 픽스처로 격리
"""
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


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
