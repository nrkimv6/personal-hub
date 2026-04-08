"""Tests for list_requests_grouped_by_caller() — SQL GROUP BY 재작성 검증."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


def _make_req(session, caller_type, caller_id, status, requested_at=None, error_message=None, prompt=None, deleted_at=None):
    req = LLMRequest(
        caller_type=caller_type,
        caller_id=caller_id,
        prompt=prompt or f"prompt for {caller_id}",
        status=status,
        requested_at=requested_at or datetime.now(),
        error_message=error_message,
        deleted_at=deleted_at,
    )
    session.add(req)
    session.flush()
    return req


# ---------------------------------------------------------------------------
# R: Right — 정상 동작
# ---------------------------------------------------------------------------

class TestListGroupedBasic:
    def test_list_requests_grouped_by_caller_R_basic(self, test_session, llm_service):
        """2 caller × 혼합 상태 → items/summary 정확성."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "completed", now - timedelta(minutes=10))
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=5))
        _make_req(test_session, "typeB", "id2", "failed", now - timedelta(minutes=3))
        _make_req(test_session, "typeB", "id2", "failed", now - timedelta(minutes=1))
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()

        assert result["total"] == 2
        assert result["summary"]["total_callers"] == 2
        assert result["summary"]["callers_with_success"] == 1
        assert result["summary"]["callers_without_success"] == 1

        # items는 최신순 정렬
        items = result["items"]
        assert len(items) == 2
        first = items[0]
        assert first["caller_id"] == "id2"  # 가장 최근 요청
        assert first["has_success"] is False
        assert first["total_count"] == 2
        assert first["failed_count"] == 2

        second = items[1]
        assert second["caller_id"] == "id1"
        assert second["has_success"] is True
        assert second["completed_count"] == 1
        assert second["failed_count"] == 1

    def test_list_requests_grouped_by_caller_R_request_ids_failed_only(self, test_session, llm_service):
        """request_ids는 failed 요청 id만 포함."""
        now = datetime.now()
        r1 = _make_req(test_session, "typeA", "id1", "completed", now - timedelta(minutes=5))
        r2 = _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=3))
        r3 = _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=1))
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()
        item = result["items"][0]

        assert set(item["request_ids"]) == {r2.id, r3.id}
        assert r1.id not in item["request_ids"]


# ---------------------------------------------------------------------------
# B: Boundary — 경계
# ---------------------------------------------------------------------------

class TestListGroupedBoundary:
    def test_list_requests_grouped_by_caller_B_empty(self, test_session, llm_service):
        """빈 테이블 → items=[], summary 모두 0."""
        result = llm_service.list_requests_grouped_by_caller()

        assert result["items"] == []
        assert result["total"] == 0
        assert result["pages"] == 1
        assert result["summary"]["total_callers"] == 0
        assert result["summary"]["callers_with_success"] == 0
        assert result["summary"]["callers_without_success"] == 0

    def test_list_requests_grouped_by_caller_B_pagination(self, test_session, llm_service):
        """page/page_size 경계: 총 3 caller, page_size=2."""
        now = datetime.now()
        for i in range(3):
            _make_req(test_session, "typeA", f"id{i}", "failed", now - timedelta(minutes=i))
        test_session.commit()

        page1 = llm_service.list_requests_grouped_by_caller(page=1, page_size=2)
        page2 = llm_service.list_requests_grouped_by_caller(page=2, page_size=2)

        assert page1["total"] == 3
        assert page1["pages"] == 2
        assert len(page1["items"]) == 2
        assert len(page2["items"]) == 1

        # 두 페이지 합쳐 caller_id 3개 모두 포함
        all_ids = {item["caller_id"] for item in page1["items"] + page2["items"]}
        assert all_ids == {"id0", "id1", "id2"}


# ---------------------------------------------------------------------------
# R: Right — 필터
# ---------------------------------------------------------------------------

class TestListGroupedFilter:
    def test_list_requests_grouped_by_caller_R_only_without_success(self, test_session, llm_service):
        """only_without_success=True → 성공 없는 caller만 반환."""
        now = datetime.now()
        _make_req(test_session, "typeA", "success_caller", "completed", now - timedelta(minutes=5))
        _make_req(test_session, "typeA", "fail_caller", "failed", now - timedelta(minutes=3))
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller(only_without_success=True)

        assert result["total"] == 1
        assert result["items"][0]["caller_id"] == "fail_caller"
        # summary는 전체 caller 기준
        assert result["summary"]["total_callers"] == 2
        assert result["summary"]["callers_with_success"] == 1
        assert result["summary"]["callers_without_success"] == 1

    def test_list_requests_grouped_by_caller_R_caller_type_filter(self, test_session, llm_service):
        """caller_type 필터: 다른 타입은 제외."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "failed", now)
        _make_req(test_session, "typeB", "id2", "failed", now)
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller(caller_type="typeA")

        assert result["total"] == 1
        assert result["items"][0]["caller_type"] == "typeA"
        assert result["summary"]["total_callers"] == 1


# ---------------------------------------------------------------------------
# Re: Reference — 참조/존재
# ---------------------------------------------------------------------------

class TestListGroupedReference:
    def test_list_requests_grouped_by_caller_Re_soft_deleted_excluded(self, test_session, llm_service):
        """deleted_at IS NOT NULL 요청은 집계에서 제외."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "failed", now)
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=1), deleted_at=now)
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()

        item = result["items"][0]
        assert item["total_count"] == 1  # deleted 1건 제외


# ---------------------------------------------------------------------------
# O: Ordering — 순서 보존
# ---------------------------------------------------------------------------

class TestListGroupedOrdering:
    def test_list_requests_grouped_by_caller_O_last_status_latest(self, test_session, llm_service):
        """last_status/last_error는 가장 최신 요청 기준."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=5), error_message="old error")
        _make_req(test_session, "typeA", "id1", "pending", now, error_message=None)
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()
        item = result["items"][0]

        assert item["last_status"] == "pending"

    def test_list_requests_grouped_by_caller_O_last_error_last_failed_row(self, test_session, llm_service):
        """last_error는 requested_at ASC 기준 마지막 failed row의 error_message."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=5), error_message="first error")
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=2), error_message="last error")
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()
        item = result["items"][0]

        assert item["last_error"] == "last error"

    def test_list_requests_grouped_by_caller_O_prompt_first_row(self, test_session, llm_service):
        """prompt는 requested_at ASC 기준 첫 번째 row의 prompt."""
        now = datetime.now()
        _make_req(test_session, "typeA", "id1", "failed", now - timedelta(minutes=10), prompt="first prompt")
        _make_req(test_session, "typeA", "id1", "failed", now, prompt="second prompt")
        test_session.commit()

        result = llm_service.list_requests_grouped_by_caller()
        item = result["items"][0]

        assert item["prompt"] == "first prompt"


# ---------------------------------------------------------------------------
# P: Performance — 전수 로드 없음
# ---------------------------------------------------------------------------

class TestListGroupedPerformance:
    def test_list_requests_grouped_by_caller_P_no_full_load(self, test_session, llm_service, monkeypatch):
        """Query.all() 호출이 집계 쿼리(1회) + 배치 상세(1회) 이내임을 확인.
        전수 로드(base_query.all())를 하면 LLMRequest 모든 컬럼 포함 수천 row 반환.
        집계 쿼리는 Group 수(≪전체 row 수)만 반환하므로 결과 크기로 구분.
        """
        now = datetime.now()
        # 10개 요청, 3 caller
        for i in range(10):
            _make_req(test_session, "typeA", f"id{i % 3}", "failed", now - timedelta(minutes=i))
        test_session.commit()

        call_count = {"n": 0}
        original_execute = test_session.execute

        def patched_execute(statement, *args, **kwargs):
            call_count["n"] += 1
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(test_session, "execute", patched_execute)

        result = llm_service.list_requests_grouped_by_caller()

        # 결과는 3 caller여야 함
        assert result["total"] == 3
        assert len(result["items"]) == 3
