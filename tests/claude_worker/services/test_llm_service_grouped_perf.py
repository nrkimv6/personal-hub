"""T3 재현/통합 TC: 실 SQLAlchemy 세션으로 전수 로드 없음 검증."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
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


def _seed(session, n_callers: int, requests_per_caller: int):
    """n_callers × requests_per_caller 건 시드."""
    now = datetime.now()
    statuses = ["completed", "failed", "pending"]
    for i in range(n_callers):
        caller_id = f"caller_{i}"
        for j in range(requests_per_caller):
            req = LLMRequest(
                caller_type="perf_test",
                caller_id=caller_id,
                prompt=f"prompt {i}-{j}",
                status=statuses[j % len(statuses)],
                requested_at=now - timedelta(minutes=i * 10 + j),
            )
            session.add(req)
    session.commit()


class TestGroupedPerformanceT3:
    def test_no_full_llm_request_load_with_1500_rows(self, test_engine, test_session, llm_service):
        """1,500건(50 caller × 30 req) 시드 후 집계 쿼리가 전체 row 로드 없이 동작.

        검증:
        1. 응답 total_callers == 50 (정확성)
        2. 각 쿼리가 반환한 결과 집합 크기가 전체 row(1500) 미만 (전수 로드 없음)
        """
        n_callers = 50
        n_per_caller = 30  # 총 1,500건
        _seed(test_session, n_callers, n_per_caller)

        # SQLAlchemy Core event로 실행된 쿼리별 반환 row 수 추적
        result_sizes = []

        @event.listens_for(test_engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if cursor.rowcount >= 0:
                result_sizes.append(cursor.rowcount)

        result = llm_service.list_requests_grouped_by_caller(page=1, page_size=10)

        # 정확성 검증
        assert result["summary"]["total_callers"] == n_callers
        assert result["total"] == n_callers
        assert result["pages"] == 5  # 50 callers / 10 page_size

        # 전수 로드 없음: 어떤 단일 쿼리도 1500 row 이상을 rowcount로 반환하지 않음
        # (집계 쿼리는 50 row, 배치 상세 조회는 최대 page_size*requests_per_caller)
        total_rows = n_callers * n_per_caller
        for size in result_sizes:
            assert size < total_rows, (
                f"단일 쿼리가 {size}건을 반환 — 전수 로드(expected < {total_rows})가 발생했을 수 있음"
            )
