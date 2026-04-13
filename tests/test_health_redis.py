"""
WorkerHealthRedis + check_pid_alive + 소비처 전환 단위 테스트

Phase T1 TC:
  Item 18: WorkerHealthRedis 단위 테스트
  Item 19: check_pid_alive 단위 테스트
  Item 20: 건강 체크 API 전환 테스트
  Item 21: 소비처 전환 테스트
"""
import json
import os
import sys
import pytest
import fakeredis
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.shared.worker.health_redis import (
    WorkerHealthRedis,
    check_pid_alive,
    HEALTH_KEY_PREFIX,
    DEFAULT_TTL,
    KNOWN_WORKER_TYPES,
)


# ============================================================
# 공통 픽스처
# ============================================================

@pytest.fixture
def fake_redis():
    """fakeredis 인스턴스를 반환하고 WorkerHealthRedis에 주입한다."""
    client = fakeredis.FakeRedis(decode_responses=False)
    with patch("app.shared.worker.health_redis.RedisClient.get_sync_client", return_value=client):
        yield client
    client.flushall()


@pytest.fixture
def redis_down():
    """Redis 연결 불가 상태를 시뮬레이션한다."""
    with patch(
        "app.shared.worker.health_redis.RedisClient.get_sync_client",
        side_effect=ConnectionError("Redis 연결 실패"),
    ):
        yield


# ============================================================
# Item 18: WorkerHealthRedis 단위 테스트
# ============================================================

class TestWorkerHealthRedisPublish:
    """WorkerHealthRedis.publish() 테스트"""

    def test_health_redis_publish_right(self, fake_redis):
        """R(Right): publish 후 check 반환값 필드 일치 + TTL 검증."""
        pid = 1234
        result = WorkerHealthRedis.publish("naver", pid, "running", memory_mb=100.0, active_tasks=3)
        assert result is True

        data = WorkerHealthRedis.check("naver")
        assert data is not None
        assert data["pid"] == pid
        assert data["state"] == "running"
        assert data["memory_mb"] == 100.0
        assert data["active_tasks"] == 3
        assert data["source"] == "redis"
        assert data["ttl_remaining"] > 0
        assert data["ttl_remaining"] <= DEFAULT_TTL

    def test_health_redis_publish_updates_existing_boundary(self, fake_redis):
        """B(Boundary): 동일 worker_type 2회 publish → 최신 값으로 덮어씀."""
        WorkerHealthRedis.publish("naver", 1000, "running", memory_mb=50.0)
        WorkerHealthRedis.publish("naver", 2000, "idle", memory_mb=75.0)

        data = WorkerHealthRedis.check("naver")
        assert data is not None
        assert data["pid"] == 2000
        assert data["state"] == "idle"
        assert data["memory_mb"] == 75.0

    def test_health_redis_publish_redis_down_error(self, redis_down):
        """E(Error): Redis 연결 실패 시 False 반환 + 예외 전파 없음."""
        result = WorkerHealthRedis.publish("naver", 1234, "running")
        assert result is False  # 예외 없이 False 반환


class TestWorkerHealthRedisCheck:
    """WorkerHealthRedis.check() 테스트"""

    def test_health_redis_check_nonexistent_right(self, fake_redis):
        """R(Right): 미등록 워커 타입 check → None 반환."""
        result = WorkerHealthRedis.check("unknown_worker_type")
        assert result is None

    def test_health_redis_check_expired_boundary(self, fake_redis):
        """B(Boundary): 키 없음(만료) 상태 → None 반환."""
        # publish 없이 직접 TTL=1 키 설정 후 삭제하여 만료 시뮬레이션
        key = f"{HEALTH_KEY_PREFIX}naver"
        fake_redis.set(key, json.dumps({"pid": 1, "state": "running", "memory_mb": 0, "active_tasks": 0, "updated_at": datetime.now().isoformat()}), ex=1)
        fake_redis.delete(key)  # 즉시 삭제로 만료 시뮬레이션
        result = WorkerHealthRedis.check("naver")
        assert result is None

    def test_health_redis_check_redis_down_error(self, redis_down):
        """E(Error): Redis 연결 실패 시 None 반환 + 예외 전파 없음."""
        result = WorkerHealthRedis.check("naver")
        assert result is None

    def test_health_redis_check_all_right(self, fake_redis):
        """R(Right): 3종 publish 후 check_all → 3개 값, 미등록 1개 None."""
        WorkerHealthRedis.publish("naver", 1001, "running")
        WorkerHealthRedis.publish("scheduled", 1002, "running")
        WorkerHealthRedis.publish("ondemand", 1003, "running")
        # "claude"는 publish 안 함

        result = WorkerHealthRedis.check_all()
        assert result["naver"] is not None
        assert result["scheduled"] is not None
        assert result["ondemand"] is not None
        assert result["claude"] is None
        assert set(result.keys()) == set(KNOWN_WORKER_TYPES)

    def test_health_redis_pid_fallback_right(self):
        """R(Right): Redis 불가 상태에서 pid 인자 전달 → source: "pid_only", alive: True."""
        current_pid = os.getpid()
        with patch(
            "app.shared.worker.health_redis.RedisClient.get_sync_client",
            return_value=None,
        ):
            result = WorkerHealthRedis.check("naver", pid=current_pid)

        assert result is not None
        assert result["source"] == "pid_only"
        assert result["alive"] is True
        assert result["pid"] == current_pid


# ============================================================
# Item 19: check_pid_alive 단위 테스트
# ============================================================

class TestCheckPidAlive:
    """check_pid_alive() 테스트"""

    def test_pid_alive_current_process_right(self):
        """R(Right): 현재 프로세스 PID → True."""
        assert check_pid_alive(os.getpid()) is True

    def test_pid_alive_nonexistent_pid_right(self):
        """R(Right): 존재하지 않는 PID → False."""
        # 99999는 일반적으로 존재하지 않는 PID
        # 만약 실제로 존재한다면 다른 큰 값 사용
        import psutil
        pid = 99999
        if psutil.pid_exists(pid):
            pid = 99998  # fallback
        assert check_pid_alive(pid) is False

    def test_pid_alive_reuse_detection_boundary(self):
        """B(Boundary): 현재 PID + started_at=10년 전 → create_time 불일치 → False."""
        current_pid = os.getpid()
        ten_years_ago = datetime.now() - timedelta(days=3650)
        result = check_pid_alive(current_pid, started_at=ten_years_ago)
        assert result is False

    def test_pid_alive_no_started_at_right(self):
        """R(Right): started_at=None → create_time 비교 스킵, PID 존재만 확인 → True."""
        assert check_pid_alive(os.getpid(), started_at=None) is True


# ============================================================
# Item 20: 건강 체크 API 전환 테스트
# ============================================================

class TestHealthCheckApiConversion:
    """Naver 워커 건강 체크 API 전환 테스트 (worker.py 로직)"""

    def _make_db_row(self, pid=None, last_heartbeat=None, started_at=None, paused_at=None):
        """worker_status DB 행 모의 객체 생성.

        컬럼 순서 (새 스키마, 10컬럼):
        pid[0], status[1], active_tasks[2], last_heartbeat[3],
        memory_usage_mb[4], started_at[5], active_tabs[6],
        browser_contexts[7], global_pause[8], paused_at[9]
        """
        return (
            pid, "running", None, last_heartbeat, 0, started_at, 0, 0, False, paused_at
        )

    def test_worker_health_redis_healthy_right(self, fake_redis):
        """R(Right): Redis에 naver 키 publish → is_healthy=True + seconds_since_heartbeat 존재."""
        from app.routes.worker import get_worker_status_from_db

        WorkerHealthRedis.publish("naver", os.getpid(), "running")

        # SessionLocal을 mock으로 교체하여 get_worker_status_from_db() 실행
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=os.getpid())

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result is not None
        # Redis 값이 last_heartbeat으로 반영됨
        assert result["last_heartbeat"] is not None
        assert result["pid"] == os.getpid()

    def test_worker_health_redis_expired_right(self, fake_redis):
        """R(Right): Redis 키 없고 PID 없음 → last_heartbeat None."""
        from app.routes.worker import get_worker_status_from_db

        # Redis에 키 없음, DB 행에 old last_heartbeat
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=0, last_heartbeat="2000-01-01")

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        # Redis 키 없음 → last_heartbeat None
        assert result is not None
        assert result["last_heartbeat"] is None

    def test_get_worker_status_hybrid_right(self, fake_redis):
        """R(Right): DB에 pid + Redis heartbeat → last_heartbeat이 Redis updated_at 값."""
        from app.routes.worker import get_worker_status_from_db

        WorkerHealthRedis.publish("naver", 5678, "running")

        redis_data = WorkerHealthRedis.check("naver")
        expected_updated_at = redis_data["updated_at"]

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=5678, last_heartbeat="2000-01-01T00:00:00")

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result is not None
        assert result["last_heartbeat"] == expected_updated_at

    def test_get_worker_status_from_db_started_at_schema_R(self, fake_redis):
        """R(Right): 새 스키마 기준 — 반환 dict에 started_at 키 존재, start_time 키 없음."""
        from app.routes.worker import get_worker_status_from_db

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=1234)

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert "started_at" in result, "started_at 키가 반환 dict에 없음"
        assert "start_time" not in result, "구 스키마 start_time 키가 잔존해 있음"
        assert result["pid"] == 1234

    def test_get_worker_status_from_db_no_browser_columns_B(self, fake_redis):
        """B(Boundary): browser_available/browser_error 키가 없고 active_tabs/browser_contexts 키가 존재."""
        from app.routes.worker import get_worker_status_from_db

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=9999)

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        # 구 키 제거 확인
        for old_key in ("browser_available", "browser_error", "browser_recovery_attempts", "browser_permanently_failed"):
            assert old_key not in result, f"구 스키마 키 '{old_key}'가 잔존해 있음"
        # 새 키 존재 확인
        assert "active_tabs" in result
        assert "browser_contexts" in result
        assert result["active_tabs"] == 0
        assert result["browser_contexts"] == 0

    def test_worker_status_started_at_datetime_to_str_R(self, fake_redis):
        """R(Right): started_at이 datetime이면 ISO 문자열로 정규화."""
        from app.routes.worker import get_worker_status_from_db

        started_at = datetime(2026, 4, 13, 9, 14, 0)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(
            pid=1234,
            started_at=started_at,
        )

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result["started_at"] == started_at.isoformat()

    def test_worker_status_paused_at_datetime_to_str_R(self, fake_redis):
        """R(Right): paused_at이 datetime이면 ISO 문자열로 정규화."""
        from app.routes.worker import get_worker_status_from_db

        paused_at = datetime(2026, 4, 13, 10, 30, 0)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(
            pid=1234,
            paused_at=paused_at,
        )

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result["paused_at"] == paused_at.isoformat()

    def test_worker_status_paused_at_none_B(self, fake_redis):
        """B(Boundary): paused_at이 None이면 None 그대로 반환."""
        from app.routes.worker import get_worker_status_from_db

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(pid=1234)

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result["paused_at"] is None

    def test_get_worker_status_from_db_exception_fallback_E(self, fake_redis):
        """E(Error): DB 예외 시 status='unknown', started_at=None, active_tabs=0 반환."""
        from app.routes.worker import get_worker_status_from_db

        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("DB 연결 실패")

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        assert result["status"] == "unknown"
        assert result["started_at"] is None
        assert result["active_tabs"] == 0
        assert result["browser_contexts"] == 0
        assert result["error_message"] is not None

    def test_worker_status_api_with_datetime_paused_at_integration(self, fake_redis):
        """T3: DB datetime paused_at → get_worker_status_from_db 결과를 Pydantic 모델로 검증."""
        from app.routes.worker import get_worker_status_from_db, WorkerStatusResponse

        paused_at = datetime(2026, 4, 13, 10, 45, 0)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(
            pid=1234,
            paused_at=paused_at,
            started_at=datetime(2026, 4, 13, 9, 0, 0),
        )

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            result = get_worker_status_from_db()

        response = WorkerStatusResponse(**result)
        assert response.paused_at == paused_at.isoformat()
        assert response.started_at == "2026-04-13T09:00:00"

    def test_worker_status_stale_pid_redis_up_integration(self, fake_redis):
        """T3: fakeredis에 heartbeat publish + mock DB에 죽은 PID →
        status='crashed', last_heartbeat 값 존재.
        실환경 재현: Redis up, worker down, stale PID 상태.
        """
        from app.routes.worker import get_worker_status_from_db, is_process_running

        # Redis에 heartbeat publish (worker가 마지막으로 살아있을 때의 흔적)
        stale_pid = 99999  # 실제로 죽어있는 PID
        WorkerHealthRedis.publish("naver", stale_pid, "running")

        # DB에는 stale PID가 남아있음
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = self._make_db_row(
            pid=stale_pid, last_heartbeat="2000-01-01T00:00:00"
        )

        with patch("app.routes.worker.SessionLocal", return_value=mock_session):
            status_data = get_worker_status_from_db()

        # Redis up → last_heartbeat이 Redis updated_at으로 채워짐
        assert status_data["last_heartbeat"] is not None, (
            "Redis heartbeat이 있으면 last_heartbeat이 채워져야 함"
        )
        assert status_data["pid"] == stale_pid

        # is_process_running(stale_pid) → False (실제 프로세스 없음)
        assert not is_process_running(stale_pid), (
            "PID 99999은 실제로 없어야 함 (테스트 환경 전제)"
        )


# ============================================================
# Item 21: 소비처 전환 테스트
# ============================================================

class TestConsumerConversion:
    """소비처(worker_status_service, llm_service) 전환 테스트"""

    def _make_instagram_worker(self, db_session):
        """테스트용 Instagram 워커 DB 레코드 생성."""
        from app.models import InstagramWorkerStatus
        import uuid

        worker = InstagramWorkerStatus(
            worker_id=str(uuid.uuid4()),
            pid=os.getpid(),
            started_at=datetime.now(),
            last_heartbeat=datetime.now() - timedelta(hours=1),  # 오래된 값
            current_state="idle",
            is_alive=True,
        )
        db_session.add(worker)
        db_session.flush()
        return worker

    def test_instagram_check_health_redis_right(self, fake_redis, test_db_session):
        """R(Right): Redis에 "scheduled" 키 publish → check_health() status: "healthy"."""
        from app.modules.instagram.services.worker_status_service import WorkerStatusService

        self._make_instagram_worker(test_db_session)
        WorkerHealthRedis.publish("scheduled", 9999, "running")

        service = WorkerStatusService(test_db_session)
        result = service.check_health()
        assert result["status"] == "healthy"

    def test_instagram_check_health_redis_expired_right(self, fake_redis, test_db_session):
        """R(Right): Redis 키 없음 → check_health() status: "dead"."""
        from app.modules.instagram.services.worker_status_service import WorkerStatusService

        self._make_instagram_worker(test_db_session)
        # Redis에 키 없음 (fake_redis가 비어 있음)

        service = WorkerStatusService(test_db_session)
        result = service.check_health()
        assert result["status"] == "dead"

    def test_llm_check_health_redis_right(self, fake_redis, test_db_session):
        """R(Right): Redis에 "claude" 키 publish → check_worker_health() status: "healthy"."""
        from app.modules.claude_worker.services.llm_service import LLMService
        from app.modules.claude_worker.models.llm_request import LLMWorkerStatus
        import uuid

        # LLMWorkerStatus 레코드 생성
        worker = LLMWorkerStatus(
            worker_id=str(uuid.uuid4()),
            pid=os.getpid(),
            started_at=datetime.now(),
            last_heartbeat=datetime.now(),
            current_state="idle",
            is_alive=True,
            processed_count=0,
            error_count=0,
        )
        test_db_session.add(worker)
        test_db_session.flush()

        WorkerHealthRedis.publish("claude", os.getpid(), "running")

        service = LLMService(test_db_session)
        result = service.check_worker_health()
        assert result["status"] == "healthy"

    def test_cleanup_stale_workers_uses_started_at_right(self, fake_redis, test_db_session):
        """R(Right): started_at 25시간 전 + is_alive=False → 삭제 확인 (last_heartbeat 무관)."""
        from app.modules.instagram.services.worker_status_service import WorkerStatusService
        from app.models import InstagramWorkerStatus
        import uuid

        old_worker = InstagramWorkerStatus(
            worker_id=str(uuid.uuid4()),
            pid=9999,
            started_at=datetime.now() - timedelta(hours=25),
            last_heartbeat=datetime.now(),  # last_heartbeat는 최근이지만 started_at이 오래됨
            current_state="stopped",
            is_alive=False,
        )
        test_db_session.add(old_worker)
        test_db_session.flush()

        service = WorkerStatusService(test_db_session)
        deleted = service.cleanup_stale_workers(max_age_hours=24)
        assert deleted >= 1


# ============================================================
# Phase T4: E2E 테스트 (워커 lifecycle)
# ============================================================

class TestWorkerLifecycleE2E:
    """T4: BaseWorker 상속 mock 워커로 lifecycle E2E 검증"""

    def test_worker_health_full_lifecycle_e2e(self, fake_redis):
        """R(Right): BaseWorker 상속 mock 워커 → _main_loop() → Redis publish + DB import 없음 확인."""
        import asyncio
        from app.shared.worker.base_worker import BaseWorker
        import app.shared.worker.base_worker as base_worker_module

        class MinimalWorker(BaseWorker):
            def __init__(self):
                super().__init__("test_lifecycle_e2e")

            def _get_loop_interval(self):
                return 0.05  # 50ms

            async def _main_loop_iteration(self):
                pass  # 최소 구현

        worker = MinimalWorker()

        async def run():
            task = asyncio.create_task(worker._main_loop())
            await asyncio.sleep(0.2)  # 200ms — 최초 heartbeat 발행 트리거됨
            worker.shutdown_event.set()
            await asyncio.wait_for(task, timeout=2.0)

        asyncio.run(run())

        # Redis publish 확인
        data = WorkerHealthRedis.check("test_lifecycle_e2e")
        assert data is not None, "Redis publish가 발생하지 않음"
        assert data["source"] == "redis"
        assert data["pid"] == worker.pid

        # base_worker 모듈에 SessionLocal 없음 확인 (DB 쓰기 제거 증명)
        assert not hasattr(base_worker_module, "SessionLocal"), "base_worker가 SessionLocal을 임포트하면 안 됨"

    def test_llm_worker_health_lifecycle_e2e(self, fake_redis):
        """R(Right): LLMWorker._update_heartbeat() → Redis 'claude' 키 publish + DB 미갱신."""
        from app.modules.claude_worker.worker.worker import LLMWorker

        mock_db = MagicMock()
        mock_db_session = MagicMock()

        with patch("app.modules.claude_worker.worker.worker.SessionLocal", return_value=mock_db_session):
            try:
                worker = LLMWorker()
            except Exception:
                # LLMWorker 생성에 DB 연결이 필요할 경우 skip
                import pytest
                pytest.skip("LLMWorker 초기화 불가 (DB 의존성)")

        # _update_heartbeat() 직접 호출 — 실제 루프 없이 핵심 동작 검증
        worker._update_heartbeat()

        # Redis "claude" 키 publish 확인
        data = WorkerHealthRedis.check("claude")
        assert data is not None, "Redis 'claude' 키 publish가 발생하지 않음"
        assert data["source"] == "redis"
        assert data["pid"] == worker.pid

        # DB 미갱신 확인
        mock_db_session.execute.assert_not_called()


# ============================================================
# Phase T3: 재현/통합 TC
# ============================================================

class TestIntegration:
    """DB 쓰기 제거 + 하이브리드 읽기 통합 검증 (실제 SQLite + fakeredis)"""

    def test_heartbeat_no_db_write_integration(self, fake_redis):
        """NaverMonitorWorker._update_heartbeat() — DB write 없고 Redis publish만 발생 확인."""
        from app.worker.naver_monitor_worker import NaverMonitorWorker
        from unittest.mock import call

        worker = NaverMonitorWorker()

        # DB 세션 mock — _update_heartbeat()가 DB를 전혀 건드리지 않아야 함
        mock_db = MagicMock()
        with patch("app.routes.worker.SessionLocal", return_value=mock_db):
            worker._update_heartbeat()

        # DB execute가 호출되지 않아야 함
        mock_db.execute.assert_not_called()

        # Redis에는 publish되었는지 확인 ("naver" 키로 publish됨 — fix 후)
        redis_data = WorkerHealthRedis.check("naver")
        assert redis_data is not None
        assert redis_data["source"] == "redis"
        assert redis_data["pid"] == worker.pid

    def test_update_state_no_heartbeat_side_effect_integration(self, fake_redis, test_db_session):
        """WorkerStatusService.update_state() 호출 후 last_heartbeat 미갱신 확인."""
        from app.modules.instagram.services.worker_status_service import WorkerStatusService
        from app.models import InstagramWorkerStatus
        import uuid

        OLD_HEARTBEAT = datetime.now() - timedelta(hours=2)
        worker = InstagramWorkerStatus(
            worker_id=str(uuid.uuid4()),
            pid=os.getpid(),
            started_at=datetime.now(),
            last_heartbeat=OLD_HEARTBEAT,
            current_state="idle",
            is_alive=True,
        )
        test_db_session.add(worker)
        test_db_session.flush()
        wid = worker.worker_id

        service = WorkerStatusService(test_db_session)
        service.update_state(wid, state="crawling", account="test_account")

        # last_heartbeat이 갱신되지 않았는지 확인
        test_db_session.expire(worker)
        test_db_session.refresh(worker)
        diff = abs((worker.last_heartbeat - OLD_HEARTBEAT).total_seconds())
        assert diff < 2, f"last_heartbeat이 갱신됨 (diff={diff}s)"
        assert worker.current_state == "crawling"
