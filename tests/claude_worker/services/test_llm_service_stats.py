"""Tests for get_stats() — GROUP BY 단일 쿼리 재작성 검증."""

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


def _make_req(session, status, deleted_at=None):
    req = LLMRequest(
        caller_type="test",
        caller_id="id1",
        prompt="p",
        status=status,
        requested_at=datetime.now(),
        deleted_at=deleted_at,
    )
    session.add(req)
    session.flush()
    return req


class TestGetStats:
    def test_get_stats_R_counts(self, test_session, llm_service):
        """상태별 카운트 정확성."""
        _make_req(test_session, "completed")
        _make_req(test_session, "completed")
        _make_req(test_session, "failed")
        _make_req(test_session, "pending")
        _make_req(test_session, "processing")
        test_session.commit()

        result = llm_service.get_stats()

        assert result["completed"] == 2
        assert result["failed"] == 1
        assert result["pending"] == 1
        assert result["processing"] == 1
        assert result["total"] == 5

    def test_get_stats_B_empty(self, test_session, llm_service):
        """빈 테이블 → 전부 0."""
        result = llm_service.get_stats()

        assert result == {
            "total": 0,
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
        }

    def test_get_stats_Re_unknown_status_ignored(self, test_session, llm_service):
        """스키마 외 status는 total에는 포함되지만 known 키에는 포함 안 됨."""
        _make_req(test_session, "completed")
        _make_req(test_session, "cancelled")  # 스키마 외
        test_session.commit()

        result = llm_service.get_stats()

        assert result["total"] == 2
        assert result["completed"] == 1
        # "cancelled" 는 known 키 없음 → 0 기본값
        assert result.get("cancelled") is None

    def test_get_stats_Re_includes_soft_deleted(self, test_session, llm_service):
        """deleted_at IS NOT NULL row도 카운트에 포함 (기존 동작 보존)."""
        now = datetime.now()
        _make_req(test_session, "completed")
        _make_req(test_session, "completed", deleted_at=now)  # soft-deleted
        test_session.commit()

        result = llm_service.get_stats()

        assert result["completed"] == 2  # soft-deleted 포함
        assert result["total"] == 2
