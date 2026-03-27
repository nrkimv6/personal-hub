"""
test_plan_recurrence.py — 반복 감지 로직 단위 테스트

Phase 6: T1 — TC 작성
Phase 7: T2 — TC 검증

RIGHT-BICEP:
- R: 정상 케이스
- B: 경계 케이스
- E: 오류/에러 케이스
- C: 교차(Cross-check) 케이스
"""
import json
import pytest
from datetime import datetime, timedelta, date
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.plan_analyze_handler import (
    _get_scope_overlap_candidates,
    save_recurrence_check_result,
    maybe_queue_recurrence_suggest,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    LLMRequest.__table__.create(bind=eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _make_record(db, filename_hash: str, category: str = "naver-booking",
                 scope: list = None, applied_at: datetime = None,
                 intent: str = "test intent", plan_date: date = None,
                 recurrence_count: int = 1, chain_root_hash: str = None) -> PlanRecord:
    r = PlanRecord(
        filename_hash=filename_hash,
        file_path=f"/path/{filename_hash}.md",
        category=category,
        scope=json.dumps(scope or []),
        applied_at=applied_at or datetime.now(),
        intent=intent,
        plan_date=plan_date or date.today(),
        recurrence_count=recurrence_count,
        chain_root_hash=chain_root_hash,
    )
    db.add(r)
    db.commit()
    return r


def _make_llm_request(db, caller_type: str, caller_id: str,
                      status: str = "pending", requested_at: datetime = None) -> LLMRequest:
    req = LLMRequest(
        caller_type=caller_type,
        caller_id=caller_id,
        prompt="test",
        status=status,
        requested_at=requested_at or datetime.now(),
        queue_name="utility",
        requested_by="test",
    )
    db.add(req)
    db.commit()
    return req


# ──────────────────────────────────────────────
# TestScopeOverlapCandidates
# ──────────────────────────────────────────────

class TestScopeOverlapCandidates:
    """_get_scope_overlap_candidates() 단위 테스트"""

    def test_scope_overlap_right_returns_matching_records(self, db):
        """R: scope 겹침 있는 레코드 반환"""
        # Arrange
        current = _make_record(db, "current_hash", scope=["plan_service.py", "routes.py"])
        matching = _make_record(db, "match_hash", scope=["plan_service.py", "other.py"])
        no_match = _make_record(db, "nomatch_hash", scope=["totally_different.py"])

        # Act
        result = _get_scope_overlap_candidates(db, current)

        # Assert
        hashes = [r.filename_hash for r in result]
        assert "match_hash" in hashes
        assert "nomatch_hash" not in hashes
        assert "current_hash" not in hashes  # 자기 자신 제외

    def test_scope_overlap_boundary_no_overlap_returns_empty(self, db):
        """B: scope 겹침 없으면 빈 리스트"""
        current = _make_record(db, "cur_hash", scope=["file_a.py"])
        _make_record(db, "other_hash", scope=["file_b.py", "file_c.py"])

        result = _get_scope_overlap_candidates(db, current)

        assert result == []

    def test_scope_overlap_error_null_scope_treated_as_empty(self, db):
        """E: scope=NULL 레코드는 교집합 0으로 처리 (빈 리스트 반환)"""
        # current 레코드 (scope 있음)
        current = _make_record(db, "cur_hash2", scope=["plan_service.py"])

        # scope=NULL 레코드
        null_scope = PlanRecord(
            filename_hash="null_scope_hash",
            file_path="/path/null.md",
            category="naver-booking",
            scope=None,
            applied_at=datetime.now(),
            intent="some intent",
            plan_date=date.today(),
        )
        db.add(null_scope)
        db.commit()

        result = _get_scope_overlap_candidates(db, current)

        assert all(r.filename_hash != "null_scope_hash" for r in result)


# ──────────────────────────────────────────────
# TestSaveRecurrenceCheckResult
# ──────────────────────────────────────────────

class TestSaveRecurrenceCheckResult:
    """save_recurrence_check_result() 단위 테스트"""

    def _make_request(self, caller_id: str):
        req = MagicMock()
        req.caller_id = caller_id
        return req

    def test_save_check_right_links_superseded_by(self, db):
        """R: is_recurrence=True 시 superseded_by 연결"""
        record = _make_record(db, "new_hash", recurrence_count=1)
        matched = _make_record(db, "old_hash", recurrence_count=1)

        result = {"result": {"is_recurrence": True, "matched_hash": "old_hash", "confidence": "high", "reason": "same bug"}}
        req = self._make_request("new_hash")

        save_recurrence_check_result(db, req, result)

        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="new_hash").first()
        assert updated.superseded_by == "old_hash"

    def test_save_check_right_increments_recurrence_count(self, db):
        """R: recurrence_count = matched + 1"""
        _make_record(db, "new_h2", recurrence_count=1)
        _make_record(db, "old_h2", recurrence_count=1)

        result = {"result": {"is_recurrence": True, "matched_hash": "old_h2", "confidence": "high", "reason": "same"}}
        req = self._make_request("new_h2")

        save_recurrence_check_result(db, req, result)

        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="new_h2").first()
        assert updated.recurrence_count == 2  # matched(1) + 1

    def test_save_check_right_propagates_chain_root_hash(self, db):
        """R: matched의 chain_root_hash 전파"""
        _make_record(db, "new_h3", recurrence_count=1)
        _make_record(db, "mid_hash", recurrence_count=2, chain_root_hash="root_hash")

        result = {"result": {"is_recurrence": True, "matched_hash": "mid_hash", "confidence": "high", "reason": "x"}}
        req = self._make_request("new_h3")

        save_recurrence_check_result(db, req, result)

        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="new_h3").first()
        assert updated.chain_root_hash == "root_hash"

    def test_save_check_boundary_false_keeps_count_one(self, db):
        """B: is_recurrence=False면 count=1 유지"""
        _make_record(db, "no_rec_hash", recurrence_count=1)

        result = {"result": {"is_recurrence": False, "matched_hash": None, "confidence": "low", "reason": "different"}}
        req = self._make_request("no_rec_hash")

        save_recurrence_check_result(db, req, result)

        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="no_rec_hash").first()
        assert updated.recurrence_count == 1
        assert updated.superseded_by is None

    def test_save_check_boundary_matched_has_no_chain_root_uses_matched_hash(self, db):
        """B: matched의 chain_root_hash=None이면 matched.filename_hash를 root로"""
        _make_record(db, "new_h4", recurrence_count=1)
        _make_record(db, "first_hash", recurrence_count=1, chain_root_hash=None)

        result = {"result": {"is_recurrence": True, "matched_hash": "first_hash", "confidence": "high", "reason": "x"}}
        req = self._make_request("new_h4")

        save_recurrence_check_result(db, req, result)

        db.expire_all()
        updated = db.query(PlanRecord).filter_by(filename_hash="new_h4").first()
        assert updated.chain_root_hash == "first_hash"


# ──────────────────────────────────────────────
# TestMaybeQueueSuggest
# ──────────────────────────────────────────────

class TestMaybeQueueSuggest:
    """maybe_queue_recurrence_suggest() 단위 테스트"""

    def test_suggest_right_queued_when_count_gte_2(self, db):
        """R: recurrence_count>=2 시 LLM 큐 등록"""
        # chain root record
        _make_record(db, "root_hash_s", recurrence_count=1)
        record = _make_record(db, "second_hash_s", recurrence_count=2, chain_root_hash="root_hash_s")

        result = maybe_queue_recurrence_suggest(db, record)

        assert result is True
        req = db.query(LLMRequest).filter_by(caller_type="plan_recurrence_suggest", caller_id="root_hash_s").first()
        assert req is not None

    def test_suggest_boundary_skipped_when_count_one(self, db):
        """B: count=1 시 스킵"""
        record = _make_record(db, "single_hash", recurrence_count=1)

        result = maybe_queue_recurrence_suggest(db, record)

        assert result is False
        req = db.query(LLMRequest).filter_by(caller_type="plan_recurrence_suggest").first()
        assert req is None

    def test_suggest_cross_dedup_within_24h(self, db):
        """C: 24시간 내 중복 요청 스킵"""
        _make_record(db, "root_hash_dup", recurrence_count=1)
        record = _make_record(db, "dup_second", recurrence_count=2, chain_root_hash="root_hash_dup")

        # 기존 pending 요청 생성
        _make_llm_request(db, "plan_recurrence_suggest", "root_hash_dup", status="pending",
                          requested_at=datetime.now() - timedelta(hours=1))

        result = maybe_queue_recurrence_suggest(db, record)

        assert result is False
        # 중복 등록 없음
        count = db.query(LLMRequest).filter_by(
            caller_type="plan_recurrence_suggest", caller_id="root_hash_dup"
        ).count()
        assert count == 1
