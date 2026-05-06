"""LLMQuotaService TC (Task 27)."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMRequest, LLMWorkerStatus


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def svc(db):
    from app.modules.claude_worker.services.repositories import (
        LLMRequestRepository, LLMWorkerRepository,
    )
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    return LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)


def _add_worker(db, worker_id="w1"):
    w = LLMWorkerStatus(
        worker_id=worker_id, pid=1, is_alive=True,
        started_at=datetime.now(), last_heartbeat=datetime.now(),
        current_state="idle",
    )
    db.add(w)
    db.flush()
    return w


class TestSetGetClearQuotaPause:
    def test_set_get_clear_quota_pause_R_cycle(self, db, svc):
        """R: set → get → clear 사이클."""
        _add_worker(db)

        # set
        paused_until = svc.set_provider_quota_pause("gemini", 60_000, "quota hit")
        assert paused_until > datetime.now()

        # get
        result = svc.get_provider_quota_pause("gemini")
        assert result is not None
        assert result > datetime.now()
        detail = svc.get_provider_quota_pause_detail("gemini")
        assert detail["paused_until"] == result
        assert "quota pause until" in detail["reason"]

        # clear
        cleared = svc.clear_provider_quota_pause("gemini")
        assert cleared is True

        # get after clear → None
        result2 = svc.get_provider_quota_pause("gemini")
        assert result2 is None

    def test_get_quota_pause_B_no_worker(self, db, svc):
        """B: 워커 없으면 None 반환."""
        result = svc.get_provider_quota_pause("claude")
        assert result is None

    def test_clear_quota_pause_B_nothing_to_clear(self, db, svc):
        """B: 없는 provider clear → False."""
        result = svc.clear_provider_quota_pause("nonexistent")
        assert result is False

    def test_set_quota_pause_B_expired_get_none(self, db, svc):
        """B: 만료된 pause → get은 None 반환."""
        _add_worker(db)
        # 이미 만료된 시각으로 직접 설정
        paused_until = svc.set_provider_quota_pause("gemini", 1)  # 1ms
        import time; time.sleep(0.01)
        result = svc.get_provider_quota_pause("gemini")
        # 1ms는 이미 지났을 수 있으므로 None이거나 not None
        # 테스트는 "만료 후에는 None" 확인
        # (실제로는 datetime.now() 비교이므로 sleep 없이는 타이밍 의존적)
        # 대신 수동으로 만료 시각을 과거로 조작
        from app.modules.claude_worker.services.repositories import LLMWorkerRepository
        repo = LLMWorkerRepository(db)
        statuses = repo.find_all()
        for s in statuses:
            s.quota_paused_until = datetime.now() - timedelta(seconds=10)
        db.commit()
        assert svc.get_provider_quota_pause("gemini") is None


class TestResetQuotaFailedRequests:
    def test_reset_quota_failed_R_resets_to_pending(self, db, svc):
        """R: quota 에러 실패 요청 → pending 전환."""
        from app.modules.claude_worker.services.repositories import LLMRequestRepository
        req = LLMRequest(
            caller_type="ct", caller_id="ci1", prompt="p", status="failed",
            provider="gemini", error_message="TerminalQuotaError occurred",
        )
        db.add(req)
        db.flush()

        count = svc.reset_quota_failed_requests("gemini")
        assert count == 1
        db.refresh(req)
        assert req.status == "pending"

    def test_reset_quota_failed_B_wrong_provider(self, db, svc):
        """B: 다른 provider 요청은 변경 안 됨."""
        req = LLMRequest(
            caller_type="ct", caller_id="ci2", prompt="p", status="failed",
            provider="claude", error_message="TerminalQuotaError occurred",
        )
        db.add(req)
        db.flush()

        count = svc.reset_quota_failed_requests("gemini")
        assert count == 0
        db.refresh(req)
        assert req.status == "failed"
