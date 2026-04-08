"""Tests for retry_failed_callers_without_success() — 재작성 후 호환성 검증."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService


@pytest.fixture
def test_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def test_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def llm_service(test_session):
    return LLMService(test_session)


def _make_req(session, caller_type, caller_id, status, error_message=None):
    req = LLMRequest(
        caller_type=caller_type,
        caller_id=caller_id,
        prompt="p",
        status=status,
        requested_at=datetime.now(),
        error_message=error_message,
    )
    session.add(req)
    session.flush()
    return req


class TestRetryFailedCallersWithoutSuccess:
    def test_retry_failed_callers_R_basic(self, test_session, llm_service):
        """성공 없는 caller의 failed 요청만 pending으로 전환, 반환 카운트 검증."""
        # caller1: failed만 (성공 없음) → 재시도 대상
        r1 = _make_req(test_session, "typeA", "caller1", "failed", error_message="err1")
        r2 = _make_req(test_session, "typeA", "caller1", "failed", error_message="err2")
        # caller2: completed 있음 → 재시도 제외
        _make_req(test_session, "typeA", "caller2", "completed")
        _make_req(test_session, "typeA", "caller2", "failed")
        test_session.commit()

        result = llm_service.retry_failed_callers_without_success()

        assert result["retried"] == 2
        assert result["callers"] == 1

        test_session.refresh(r1)
        test_session.refresh(r2)
        assert r1.status == "pending"
        assert r2.status == "pending"
        assert r1.error_message is None
        assert r2.error_message is None

    def test_retry_failed_callers_R_no_candidates(self, test_session, llm_service):
        """모든 caller가 성공 이력 있으면 retried=0."""
        _make_req(test_session, "typeA", "caller1", "completed")
        _make_req(test_session, "typeA", "caller1", "failed")
        test_session.commit()

        result = llm_service.retry_failed_callers_without_success()

        assert result["retried"] == 0
        assert result["callers"] == 0
