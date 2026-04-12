"""LLMRequestRepository TC (Task 26)."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def repo(db):
    from app.modules.claude_worker.services.repositories import LLMRequestRepository
    return LLMRequestRepository(db)


def _req(db, caller_type="ct", caller_id="ci", status="pending", queue_name="utility", provider="claude", **kw):
    r = LLMRequest(
        caller_type=caller_type,
        caller_id=caller_id,
        prompt="p",
        status=status,
        queue_name=queue_name,
        provider=provider,
        **kw,
    )
    db.add(r)
    db.flush()
    return r


class TestFindExistingPending:
    def test_find_existing_pending_R_found(self, db, repo):
        """R: pending 상태 request 존재 시 반환."""
        r = _req(db, caller_type="instagram", caller_id="123", status="pending", queue_name="utility")
        result = repo.find_existing_pending("instagram", "123", "utility")
        assert result is not None
        assert result.id == r.id

    def test_find_existing_pending_B_no_match(self, db, repo):
        """B: 매치 없을 때 None 반환."""
        _req(db, caller_type="instagram", caller_id="999", status="completed")
        result = repo.find_existing_pending("instagram", "999", "utility")
        assert result is None

    def test_find_existing_pending_B_different_queue(self, db, repo):
        """B: 다른 queue_name → None 반환."""
        _req(db, caller_type="ct", caller_id="1", status="pending", queue_name="system")
        result = repo.find_existing_pending("ct", "1", "utility")
        assert result is None


class TestFindNextPendingInQueue:
    def test_find_next_pending_R_returns_oldest(self, db, repo):
        """R: 가장 오래된 pending 반환."""
        now = datetime.now()
        r1 = _req(db, caller_id="a1", status="pending", queue_name="utility")
        r1.requested_at = now - timedelta(minutes=5)
        r2 = _req(db, caller_id="a2", status="pending", queue_name="utility")
        r2.requested_at = now - timedelta(minutes=1)
        db.flush()

        result = repo.find_next_pending_in_queue("utility", [])
        assert result.caller_id == "a1"

    def test_find_next_pending_B_exclude_providers(self, db, repo):
        """B: exclude 목록의 provider 제외."""
        _req(db, caller_id="b1", status="pending", queue_name="utility", provider="gemini")
        r2 = _req(db, caller_id="b2", status="pending", queue_name="utility", provider="claude")

        result = repo.find_next_pending_in_queue("utility", ["gemini"])
        assert result is not None
        assert result.caller_id == "b2"


class TestListWithFilters:
    def test_list_R_with_filters(self, db, repo):
        """R: status/caller_type 필터 적용."""
        _req(db, caller_type="instagram", caller_id="x1", status="completed")
        _req(db, caller_type="report", caller_id="x2", status="completed")
        _req(db, caller_type="instagram", caller_id="x3", status="failed")

        items, total = repo.list_with_filters(status="completed", caller_type="instagram", page=1, page_size=20)
        assert total == 1
        assert items[0].caller_type == "instagram"
        assert items[0].status == "completed"

    def test_list_B_pagination(self, db, repo):
        """B: 페이지네이션 경계값."""
        for i in range(5):
            _req(db, caller_id=f"pg{i}", status="pending")

        items_p1, total = repo.list_with_filters(page=1, page_size=3)
        assert total == 5
        assert len(items_p1) == 3

        items_p2, _ = repo.list_with_filters(page=2, page_size=3)
        assert len(items_p2) == 2


class TestCountByStatus:
    def test_count_by_status_R_correct(self, db, repo):
        """R: 상태별 카운트 정확성."""
        _req(db, caller_id="s1", status="pending")
        _req(db, caller_id="s2", status="pending")
        _req(db, caller_id="s3", status="completed")

        rows = repo.get_status_counts()
        counts = dict(rows)
        assert counts.get("pending", 0) == 2
        assert counts.get("completed", 0) == 1


class TestAggregateByCallerGroupby:
    def test_aggregate_by_caller_R_groupby(self, db, repo):
        """R: GROUP BY (caller_type, caller_id) 결과 구조 검증."""
        _req(db, caller_type="insta", caller_id="c1", status="completed")
        _req(db, caller_type="insta", caller_id="c1", status="failed")
        _req(db, caller_type="insta", caller_id="c2", status="pending")

        rows = repo.build_caller_aggregate_query("insta").all()
        assert len(rows) == 2
        c1_row = next(r for r in rows if r.caller_id == "c1")
        assert c1_row.total_count == 2
        assert c1_row.has_success == 1  # completed 있음
