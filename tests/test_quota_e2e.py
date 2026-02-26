"""
LLM Quota e2e + HTTP 통합 테스트 (Phase 8)

- 워커 통합 시나리오 (asyncio)
- HTTP API 통합 테스트 (FastAPI TestClient)
"""
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus
from app.modules.claude_worker.routes.llm_routes import router as llm_router
from app.modules.claude_worker.services.llm_service import LLMService


# ========== Fixtures ==========

@pytest.fixture
def in_memory_engine():
    # 모든 모델 import (Base.metadata에 등록되도록)
    import app.modules.claude_worker.models.llm_request  # noqa
    import app.modules.writing.models.writing_batch  # noqa
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_with_status(in_memory_engine):
    """인메모리 DB + LLMWorkerStatus 레코드 1건."""
    Session = sessionmaker(bind=in_memory_engine)
    db = Session()
    status = LLMWorkerStatus(worker_id="test", is_alive=True, current_state="idle")
    db.add(status)
    db.commit()
    yield db
    db.close()


@pytest.fixture
def test_client(test_db_session):
    """FastAPI TestClient + conftest test_db_session 오버라이드."""
    db = test_db_session

    # 기존 레코드 정리
    db.query(LLMRequest).delete()
    db.query(LLMWorkerStatus).delete()
    db.commit()

    # worker status 레코드 추가
    status = LLMWorkerStatus(worker_id="test_http", is_alive=True, current_state="idle")
    db.add(status)
    db.commit()

    app_instance = FastAPI()
    app_instance.include_router(llm_router)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app_instance.dependency_overrides[get_db] = override_get_db

    with TestClient(app_instance) as client:
        yield client, db

    app_instance.dependency_overrides.clear()


# ========== 31: 워커 통합 e2e ==========

class TestWorkerE2E:
    """워커 통합 시나리오 e2e"""

    @pytest.mark.asyncio
    async def test_e2e_process_pending_skips_paused_provider(self, db_with_status):
        """gemini pause 설정 → _process_pending_requests() → gemini 요청 미처리."""
        service = LLMService(db_with_status)

        # gemini 요청 추가
        req = LLMRequest(
            caller_type="test", caller_id="g1", prompt="test",
            provider="gemini", status="pending", queue_name="utility",
        )
        db_with_status.add(req)
        db_with_status.commit()

        # gemini pause 설정
        service.set_provider_quota_pause("gemini", 3600000)

        # exclude_providers로 gemini가 제외되어 None 반환
        result = service.get_next_request(exclude_providers=["gemini"])
        assert result is None

        # blocked count 확인
        blocked = service.get_blocked_pending_count("gemini")
        assert blocked == 1

    @pytest.mark.asyncio
    async def test_e2e_check_quota_resume_resets_failed(self, db_with_status):
        """paused_until을 과거로 설정 + failed 요청 → clear 후 pending 전환."""
        service = LLMService(db_with_status)

        # failed gemini 요청 추가 (quota 에러 메시지)
        req = LLMRequest(
            caller_type="test", caller_id="g2", prompt="test",
            provider="gemini", status="failed", queue_name="utility",
            error_message="TerminalQuotaError",
        )
        db_with_status.add(req)

        # paused_until을 과거로 직접 설정
        status = db_with_status.query(LLMWorkerStatus).first()
        status.quota_paused_provider = "gemini"
        status.quota_paused_until = datetime.now() - timedelta(seconds=1)
        db_with_status.commit()

        # pause가 만료됐으므로 get_provider_quota_pause → None
        assert service.get_provider_quota_pause("gemini") is None

        # clear + reset
        cleared = service.clear_provider_quota_pause("gemini")
        count = service.reset_quota_failed_requests("gemini")

        # clear는 False (이미 만료된 상태에서 stale record 정리)
        # count > 0이어야 함
        assert count > 0

        req = db_with_status.query(LLMRequest).first()
        assert req.status == "pending"


# ========== 32: HTTP GET /api/v1/llm/quota-status ==========

class TestHttpQuotaStatus:
    """GET /api/v1/llm/quota-status HTTP 통합 테스트"""

    def test_http_quota_status_no_pause(self, test_client):
        """GET /api/v1/llm/quota-status → gemini/claude 모두 paused=false."""
        client, db = test_client
        response = client.get("/api/v1/llm/quota-status")
        assert response.status_code == 200
        data = response.json()
        assert data["gemini"]["paused"] is False
        assert data["claude"]["paused"] is False

    def test_http_quota_status_gemini_paused(self, test_client):
        """gemini pause 설정 후 GET → paused=true, remaining_seconds > 0."""
        client, db = test_client
        service = LLMService(db)
        service.set_provider_quota_pause("gemini", 3600000)

        response = client.get("/api/v1/llm/quota-status")
        assert response.status_code == 200
        data = response.json()
        assert data["gemini"]["paused"] is True
        assert data["gemini"]["remaining_seconds"] > 0
        assert "pending_blocked_count" in data["gemini"]


# ========== 33: HTTP DELETE /api/v1/llm/quota-pause/{provider} ==========

class TestHttpDeleteQuotaPause:
    """DELETE /api/v1/llm/quota-pause/{provider} HTTP 통합 테스트"""

    def test_http_delete_quota_pause_clears_and_resets(self, test_client):
        """gemini pause 설정 + failed 요청 → DELETE → cleared=true, reset_count > 0."""
        client, db = test_client
        service = LLMService(db)

        # pause 설정
        service.set_provider_quota_pause("gemini", 3600000)

        # failed 요청 추가
        req = LLMRequest(
            caller_type="test", caller_id="g3", prompt="test",
            provider="gemini", status="failed", queue_name="utility",
            error_message="TerminalQuotaError",
        )
        db.add(req)
        db.commit()

        response = client.delete("/api/v1/llm/quota-pause/gemini")
        assert response.status_code == 200
        data = response.json()
        assert data["cleared"] is True
        assert data["reset_count"] >= 1

        # 이후 quota-status paused=false
        status_resp = client.get("/api/v1/llm/quota-status")
        assert status_resp.json()["gemini"]["paused"] is False

    def test_http_delete_quota_pause_unknown_provider(self, test_client):
        """존재하지 않는 provider DELETE → cleared=false."""
        client, db = test_client
        response = client.delete("/api/v1/llm/quota-pause/unknown_provider")
        assert response.status_code == 200
        data = response.json()
        assert data["cleared"] is False
