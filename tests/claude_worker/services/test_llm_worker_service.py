"""LLMWorkerService TC (Task 27)."""
import pytest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.modules.claude_worker.models.llm_request import LLMWorkerStatus


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
    from app.modules.claude_worker.services.repositories import LLMWorkerRepository
    from app.modules.claude_worker.services.llm_worker_service import LLMWorkerService
    return LLMWorkerService(LLMWorkerRepository(db), db)


class TestRegisterWorker:
    def test_register_worker_R_creates(self, db, svc):
        """R: 새 worker 등록."""
        status = svc.register_worker("worker-1", pid=1234)
        assert status.id is not None
        assert status.worker_id == "worker-1"
        assert status.pid == 1234
        assert status.is_alive is True
        assert status.current_state == "idle"

    def test_register_worker_R_deactivates_previous(self, db, svc):
        """R: 신규 등록 시 기존 alive 워커 비활성화."""
        w1 = svc.register_worker("w1", pid=100)
        w2 = svc.register_worker("w2", pid=200)
        db.refresh(w1)
        assert w1.is_alive is False
        assert w2.is_alive is True


class TestHeartbeatAndState:
    def test_update_heartbeat_R_updates_time(self, db, svc):
        """R: 하트비트 업데이트."""
        svc.register_worker("w-hb", pid=1)
        before = datetime.now()
        svc.update_heartbeat("w-hb")
        # LLMWorkerStatus 조회
        from app.modules.claude_worker.services.repositories import LLMWorkerRepository
        status = LLMWorkerRepository(db).get_by_worker_id("w-hb")
        assert status.last_heartbeat >= before

    def test_update_worker_state_R_transition(self, db, svc):
        """R: 상태 전이."""
        svc.register_worker("w-st", pid=2)
        svc.update_worker_state("w-st", "processing", request_id=42)
        from app.modules.claude_worker.services.repositories import LLMWorkerRepository
        status = LLMWorkerRepository(db).get_by_worker_id("w-st")
        assert status.current_state == "processing"
        assert status.current_request_id == 42

    def test_mark_worker_dead_R_sets_stopped(self, db, svc):
        """R: mark_worker_dead → is_alive=False, state=stopped."""
        svc.register_worker("w-dead", pid=3)
        svc.mark_worker_dead("w-dead")
        from app.modules.claude_worker.services.repositories import LLMWorkerRepository
        status = LLMWorkerRepository(db).get_by_worker_id("w-dead")
        assert status.is_alive is False
        assert status.current_state == "stopped"


class TestCheckWorkerHealth:
    def test_check_worker_health_B_no_worker(self, db, svc):
        """B: 워커 없음 → no_worker 상태."""
        result = svc.check_worker_health()
        assert result["status"] == "no_worker"

    def test_check_worker_health_B_redis_healthy(self, db, svc):
        """B: Redis heartbeat 정상 → healthy."""
        svc.register_worker("w-health", pid=4)
        with patch("app.shared.worker.health_redis.WorkerHealthRedis.check") as mock_check:
            mock_check.return_value = {"source": "redis", "ttl_remaining": 25}
            result = svc.check_worker_health()
        assert result["status"] == "healthy"

    def test_check_worker_health_B_stale_heartbeat(self, db, svc):
        """B: TTL 만료 → unhealthy."""
        svc.register_worker("w-stale", pid=5)
        with patch("app.shared.worker.health_redis.WorkerHealthRedis.check") as mock_check:
            mock_check.return_value = {"source": "redis", "ttl_remaining": 0}
            result = svc.check_worker_health()
        assert result["status"] == "unhealthy"
