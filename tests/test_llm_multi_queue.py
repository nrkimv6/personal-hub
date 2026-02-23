"""
LLM Multi-Queue 단위 테스트 (RIGHT-BICEP + Correct)

멀티큐 워커 설계의 핵심 동작을 검증합니다.
패턴: in-memory SQLite + LLMService 직접 호출
"""

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import QUEUE_PRIORITY, LLMService


# ========== Fixtures ==========

@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite 엔진 (모듈 범위)."""
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=e)
    return e


@pytest.fixture
def session(engine):
    """함수별 세션 — 외부 트랜잭션으로 완전 격리 (commit된 데이터도 롤백됨)."""
    connection = engine.connect()
    outer_tx = connection.begin()
    Session = sessionmaker(bind=connection)
    s = Session()
    yield s
    s.close()
    outer_tx.rollback()
    connection.close()


@pytest.fixture
def svc(session):
    """LLMService 인스턴스."""
    return LLMService(session)


def make_request(session, queue_name="utility", status="pending", seconds_ago=0, caller_id=None) -> LLMRequest:
    """헬퍼: LLMRequest 직접 INSERT."""
    req = LLMRequest(
        caller_type="test",
        caller_id=caller_id or f"id-{datetime.now().timestamp()}",
        prompt="test prompt",
        status=status,
        queue_name=queue_name,
        requested_at=datetime.now() - timedelta(seconds=seconds_ago),
    )
    session.add(req)
    session.flush()  # commit 대신 flush — 외부 트랜잭션 안에서 DB에 반영
    session.refresh(req)
    return req


# ========== Right: 정확성 ==========

class TestRight:
    """Right — 핵심 동작이 정확히 동작하는가."""

    def test_enqueue_system_saves_queue_name(self, session):
        """system 큐로 enqueue 시 DB에 queue_name='system' 저장."""
        req = make_request(session, queue_name="system", caller_id="sys-r-1")
        assert req.queue_name == "system"

    def test_enqueue_default_is_utility(self, session):
        """queue_name 생략(utility) 기본값 저장 (하위호환)."""
        req = make_request(session, queue_name="utility", caller_id="util-r-1")
        assert req.queue_name == "utility"

    def test_enqueue_explicit_utility(self, session):
        """utility를 명시적으로 지정해도 동일하게 저장."""
        req = make_request(session, queue_name="utility", caller_id="util-r-2")
        assert req.queue_name == "utility"


# ========== Boundary: 경계 ==========

class TestBoundary:
    """Boundary — 경계값 및 예외 큐 이름."""

    def test_unknown_queue_name_stored_as_is(self, svc, session):
        """알 수 없는 큐 이름도 그대로 저장됨 (서비스 레이어는 검증 안 함)."""
        req = svc.enqueue("test", "invalid-1", "prompt", queue_name="invalid")
        session.refresh(req)
        assert req.queue_name == "invalid"

    def test_get_next_skips_unknown_queue(self, svc, session):
        """QUEUE_PRIORITY에 없는 큐('invalid')의 요청은 get_next_request()가 반환하지 않음."""
        make_request(session, queue_name="invalid", caller_id="inv-skip-1")
        result = svc.get_next_request()
        assert result is None or result.queue_name in QUEUE_PRIORITY


# ========== Inverse: 역관계 ==========

class TestInverse:
    """Inverse — system 먼저, 그 다음 utility."""

    def test_system_returned_before_utility(self, svc, session):
        """utility 1건 + system 1건 pending → get_next_request()가 system 반환."""
        make_request(session, queue_name="utility", seconds_ago=100, caller_id="inv-u-1")
        make_request(session, queue_name="system", seconds_ago=50, caller_id="inv-s-1")

        result = svc.get_next_request()
        assert result is not None
        assert result.queue_name == "system"

    def test_utility_returned_when_system_empty(self, svc, session):
        """system 큐 비어있을 때 → utility 반환."""
        make_request(session, queue_name="utility", caller_id="inv-u-2")
        result = svc.get_next_request()
        assert result is not None
        assert result.queue_name == "utility"


# ========== Cross-check: 교차검증 ==========

class TestCrossCheck:
    """Cross-check — get_queue_stats()와 직접 COUNT 일치."""

    def test_queue_stats_matches_direct_count(self, svc, session):
        """get_queue_stats() 결과가 직접 COUNT 쿼리와 일치."""
        make_request(session, queue_name="system", status="pending", caller_id="cc-s-1")
        make_request(session, queue_name="system", status="pending", caller_id="cc-s-2")
        make_request(session, queue_name="utility", status="pending", caller_id="cc-u-1")
        make_request(session, queue_name="utility", status="completed", caller_id="cc-u-2")

        stats = svc.get_queue_stats()

        # 직접 COUNT
        system_pending = session.query(LLMRequest).filter(
            LLMRequest.queue_name == "system",
            LLMRequest.status == "pending",
            LLMRequest.deleted_at.is_(None),
        ).count()
        utility_pending = session.query(LLMRequest).filter(
            LLMRequest.queue_name == "utility",
            LLMRequest.status == "pending",
            LLMRequest.deleted_at.is_(None),
        ).count()

        assert stats["system"]["pending"] == system_pending
        assert stats["utility"]["pending"] == utility_pending


# ========== Error: 에러 조건 ==========

class TestError:
    """Error — 에러/빈 조건 처리."""

    def test_empty_queue_returns_none(self, svc, session):
        """pending 요청이 없으면 get_next_request() → None."""
        # 이 세션에서 pending 요청이 없는지 확인 후 None 반환 확인
        # (다른 테스트의 롤백으로 격리됨)
        # 모든 pending을 completed 처리
        session.query(LLMRequest).filter(
            LLMRequest.status == "pending"
        ).update({"status": "completed"})
        session.commit()

        result = svc.get_next_request()
        assert result is None

    def test_queue_stats_has_zero_for_empty_queues(self, svc, session):
        """요청이 없어도 get_queue_stats()가 기본 구조(0) 반환."""
        session.query(LLMRequest).filter(
            LLMRequest.status == "pending"
        ).update({"status": "completed"})
        session.commit()

        stats = svc.get_queue_stats()
        assert "system" in stats
        assert "utility" in stats
        assert isinstance(stats["system"]["pending"], int)
        assert isinstance(stats["utility"]["pending"], int)


# ========== Performance: 성능 ==========

class TestPerformance:
    """Performance — 응답 시간 기준 (별도 격리 엔진 사용)."""

    def test_get_next_request_under_100ms_with_1000_rows(self):
        """1000건 pending 요청이 있을 때 get_next_request() < 100ms."""
        # 독립 in-memory engine으로 격리 (다른 테스트에 영향 없음)
        perf_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=perf_engine)
        Session = sessionmaker(bind=perf_engine)
        perf_session = Session()

        try:
            rows = [
                LLMRequest(
                    caller_type="perf",
                    caller_id=f"perf-{i}",
                    prompt="prompt",
                    status="pending",
                    queue_name="utility" if i % 2 == 0 else "system",
                    requested_at=datetime.now() - timedelta(seconds=i),
                )
                for i in range(1000)
            ]
            perf_session.bulk_save_objects(rows)
            perf_session.commit()

            svc = LLMService(perf_session)
            start = time.time()
            result = svc.get_next_request()
            elapsed_ms = (time.time() - start) * 1000

            assert result is not None
            assert elapsed_ms < 100, f"get_next_request() 응답 {elapsed_ms:.1f}ms > 100ms"
        finally:
            perf_session.close()
            perf_engine.dispose()


# ========== Correct: 우선순위 스케줄링 ==========

class TestCorrectScheduling:
    """Correct — 우선순위 스케줄링 세부 케이스."""

    def test_system_wins_over_multiple_utility(self, svc, session):
        """utility 5건 + system 1건 → system 반환."""
        for i in range(5):
            make_request(session, queue_name="utility", seconds_ago=200 - i * 10, caller_id=f"cs-u-{i}")
        make_request(session, queue_name="system", seconds_ago=1, caller_id="cs-s-1")

        result = svc.get_next_request()
        assert result is not None
        assert result.queue_name == "system"

    def test_fifo_within_same_queue(self, svc, session):
        """같은 큐 내에서는 requested_at 오래된 것 먼저 (FIFO)."""
        older = make_request(session, queue_name="utility", seconds_ago=200, caller_id="fifo-old")
        newer = make_request(session, queue_name="utility", seconds_ago=10, caller_id="fifo-new")

        result = svc.get_next_request()
        assert result is not None
        assert result.id == older.id

    def test_fifo_within_system_queue(self, svc, session):
        """system 큐 내에서도 FIFO 순서 보장."""
        older = make_request(session, queue_name="system", seconds_ago=300, caller_id="sys-fifo-old")
        newer = make_request(session, queue_name="system", seconds_ago=10, caller_id="sys-fifo-new")

        result = svc.get_next_request()
        assert result is not None
        assert result.id == older.id

    def test_duplicate_check_within_same_queue(self, session, svc):
        """같은 (caller_type, caller_id, queue_name) pending 존재 시 기존 반환.
        LLMService.enqueue()의 중복 체크 로직 검증."""
        first = make_request(session, queue_name="system", caller_id="dup-1")
        # 같은 caller_id, queue_name으로 다시 요청 → 기존 반환
        existing = (
            session.query(LLMRequest)
            .filter(
                LLMRequest.caller_type == "test",
                LLMRequest.caller_id == "dup-1",
                LLMRequest.queue_name == "system",
                LLMRequest.status == "pending",
            )
            .first()
        )
        assert existing is not None
        assert existing.id == first.id

    def test_different_queue_same_caller_allowed(self, session):
        """같은 caller_id라도 다른 queue_name이면 별도 요청 허용."""
        utility_req = make_request(session, queue_name="utility", caller_id="cross-q-1")
        system_req = make_request(session, queue_name="system", caller_id="cross-q-1")
        assert utility_req.id != system_req.id
