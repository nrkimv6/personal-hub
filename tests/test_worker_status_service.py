"""
Instagram Worker Status Service 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트

CORRECT 조건 적용:
- Conformance: 형식 준수
- Ordering: 순서 보장
- Range: 범위 검증
- Reference: 참조 검증
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- WorkerStatusService (워커 상태 관리)
- 헬스체크 로직
- 상태 업데이트
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.instagram.services.worker_status_service import (
    WorkerStatusService,
    HEALTHY_THRESHOLD,
    WARNING_THRESHOLD,
)


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    return MagicMock()


@pytest.fixture
def mock_worker():
    """Mock 워커 상태 객체"""
    worker = MagicMock()
    worker.worker_id = "test-worker-123"
    worker.pid = 12345
    worker.started_at = datetime.now() - timedelta(hours=1)
    worker.last_heartbeat = datetime.now()
    worker.current_state = "idle"
    worker.current_account = None
    worker.current_run_id = None
    worker.is_alive = True
    return worker


@pytest.fixture
def service(mock_db):
    """WorkerStatusService 인스턴스"""
    return WorkerStatusService(mock_db)


# ============================================================
# WorkerStatusService 테스트 - Right (결과 검증)
# ============================================================

class TestWorkerStatusServiceRight:
    """워커 상태 서비스 결과 검증 테스트"""

    def test_register_worker_returns_worker_status(self, service, mock_db):
        """register_worker가 워커 상태 객체를 반환"""
        # Setup
        mock_db.query.return_value.filter.return_value.update.return_value = 0

        # Execute
        result = service.register_worker("test-worker-123")

        # Verify
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_register_worker_with_auto_id(self, service, mock_db):
        """worker_id 없이 호출 시 UUID 자동 생성"""
        mock_db.query.return_value.filter.return_value.update.return_value = 0

        result = service.register_worker()

        # add가 호출되었어야 함
        mock_db.add.assert_called_once()

    def test_update_heartbeat_updates_time(self, service, mock_db, mock_worker):
        """update_heartbeat가 last_heartbeat를 업데이트"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_worker
        old_heartbeat = mock_worker.last_heartbeat

        result = service.update_heartbeat("test-worker-123")

        assert result == mock_worker
        mock_db.commit.assert_called_once()

    def test_update_state_changes_worker_state(self, service, mock_db, mock_worker):
        """update_state가 워커 상태를 변경"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_worker

        result = service.update_state(
            worker_id="test-worker-123",
            state="crawling",
            account="testaccount",
            run_id=42
        )

        assert mock_worker.current_state == "crawling"
        assert mock_worker.current_account == "testaccount"
        assert mock_worker.current_run_id == 42
        mock_db.commit.assert_called_once()

    def test_mark_dead_sets_is_alive_false(self, service, mock_db, mock_worker):
        """mark_dead가 is_alive를 False로 설정"""
        mock_db.query.return_value.filter.return_value.first.return_value = mock_worker

        result = service.mark_dead("test-worker-123")

        assert mock_worker.is_alive is False
        assert mock_worker.current_state == "stopped"
        assert mock_worker.current_account is None
        assert mock_worker.current_run_id is None

    def test_get_current_status_returns_alive_worker(self, service, mock_db, mock_worker):
        """get_current_status가 활성 워커 반환"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.get_current_status()

        assert result == mock_worker


# ============================================================
# 헬스체크 테스트 - Boundary (경계값)
# ============================================================

class TestHealthCheckBoundary:
    """헬스체크 경계값 테스트"""

    def test_check_health_no_worker(self, service, mock_db):
        """워커가 없을 때 no_worker 상태"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = service.check_health()

        assert result["status"] == "no_worker"
        assert result["worker_id"] is None
        assert "No active worker" in result["message"]

    def test_check_health_healthy_within_threshold(self, service, mock_db, mock_worker):
        """HEALTHY_THRESHOLD 이내면 healthy"""
        # 30초 전 heartbeat
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=30)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        assert result["status"] == "healthy"
        assert result["heartbeat_age_seconds"] <= HEALTHY_THRESHOLD

    def test_check_health_exactly_at_healthy_threshold(self, service, mock_db, mock_worker):
        """정확히 HEALTHY_THRESHOLD일 때 healthy"""
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=HEALTHY_THRESHOLD)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        assert result["status"] == "healthy"

    def test_check_health_warning_above_healthy_threshold(self, service, mock_db, mock_worker):
        """HEALTHY_THRESHOLD 초과, WARNING_THRESHOLD 이하면 warning"""
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=90)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        assert result["status"] == "warning"
        assert result["heartbeat_age_seconds"] > HEALTHY_THRESHOLD
        assert result["heartbeat_age_seconds"] <= WARNING_THRESHOLD

    def test_check_health_exactly_at_warning_threshold(self, service, mock_db, mock_worker):
        """정확히 WARNING_THRESHOLD일 때 warning"""
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=WARNING_THRESHOLD)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        assert result["status"] == "warning"

    def test_check_health_dead_above_warning_threshold(self, service, mock_db, mock_worker):
        """WARNING_THRESHOLD 초과면 dead"""
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=150)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        assert result["status"] == "dead"
        assert result["heartbeat_age_seconds"] > WARNING_THRESHOLD


# ============================================================
# 상태 업데이트 테스트 - Time (시간 관련)
# ============================================================

class TestWorkerStatusTime:
    """워커 상태 시간 관련 테스트"""

    def test_get_status_with_computed_fields_calculates_uptime(self, service, mock_db, mock_worker):
        """get_status_with_computed_fields가 uptime 계산"""
        # 1시간 전에 시작
        mock_worker.started_at = datetime.now() - timedelta(hours=1)
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=5)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.get_status_with_computed_fields()

        assert result is not None
        assert "uptime_seconds" in result
        # 1시간 = 3600초 (약간의 오차 허용)
        assert 3500 < result["uptime_seconds"] < 3700

    def test_get_status_with_computed_fields_calculates_heartbeat_age(self, service, mock_db, mock_worker):
        """get_status_with_computed_fields가 heartbeat 경과 시간 계산"""
        mock_worker.started_at = datetime.now() - timedelta(hours=1)
        mock_worker.last_heartbeat = datetime.now() - timedelta(seconds=30)
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.get_status_with_computed_fields()

        assert result is not None
        assert "heartbeat_age_seconds" in result
        # 30초 정도 (약간의 오차 허용)
        assert 25 < result["heartbeat_age_seconds"] < 35

    def test_get_status_with_computed_fields_returns_none_when_no_worker(self, service, mock_db):
        """워커가 없으면 None 반환"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = service.get_status_with_computed_fields()

        assert result is None


# ============================================================
# 워커 정리 테스트 - Reference (참조 검증)
# ============================================================

class TestCleanupStaleWorkers:
    """오래된 워커 정리 테스트"""

    def test_cleanup_stale_workers_deletes_old_dead_workers(self, service, mock_db):
        """cleanup_stale_workers가 오래된 dead 워커 삭제"""
        mock_db.query.return_value.filter.return_value.delete.return_value = 5

        result = service.cleanup_stale_workers(max_age_hours=24)

        assert result == 5
        mock_db.commit.assert_called_once()

    def test_cleanup_stale_workers_respects_max_age(self, service, mock_db):
        """max_age_hours 파라미터 적용"""
        mock_db.query.return_value.filter.return_value.delete.return_value = 0

        service.cleanup_stale_workers(max_age_hours=48)

        # filter가 호출되었어야 함
        mock_db.query.return_value.filter.assert_called()

    def test_cleanup_stale_workers_returns_zero_when_nothing_deleted(self, service, mock_db):
        """삭제된 것이 없으면 0 반환"""
        mock_db.query.return_value.filter.return_value.delete.return_value = 0

        result = service.cleanup_stale_workers()

        assert result == 0


# ============================================================
# 에러 조건 테스트 - Error
# ============================================================

class TestWorkerStatusError:
    """에러 조건 테스트"""

    def test_update_heartbeat_nonexistent_worker(self, service, mock_db):
        """존재하지 않는 워커 heartbeat 업데이트 시 None 반환"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.update_heartbeat("nonexistent-worker")

        assert result is None

    def test_update_state_nonexistent_worker(self, service, mock_db):
        """존재하지 않는 워커 상태 업데이트 시 None 반환"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.update_state("nonexistent-worker", "crawling")

        assert result is None

    def test_mark_dead_nonexistent_worker(self, service, mock_db):
        """존재하지 않는 워커 dead 표시 시 None 반환"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = service.mark_dead("nonexistent-worker")

        assert result is None


# ============================================================
# 기존 워커 처리 테스트 - Inverse
# ============================================================

class TestWorkerRegistrationInverse:
    """워커 등록 역관계 테스트"""

    def test_register_worker_marks_existing_workers_dead(self, service, mock_db):
        """새 워커 등록 시 기존 alive 워커들이 dead로 표시"""
        # 기존 워커가 2개 있다고 가정
        mock_db.query.return_value.filter.return_value.update.return_value = 2

        service.register_worker("new-worker")

        # update가 호출되었어야 함 (is_alive=False로)
        mock_db.query.return_value.filter.return_value.update.assert_called()


# ============================================================
# 헬스체크 결과 필드 테스트 - Conformance
# ============================================================

class TestHealthCheckConformance:
    """헬스체크 결과 형식 테스트"""

    def test_check_health_returns_required_fields(self, service, mock_db, mock_worker):
        """check_health가 필수 필드 포함"""
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker

        result = service.check_health()

        required_fields = ["status", "worker_id", "last_heartbeat",
                          "heartbeat_age_seconds", "current_state", "message"]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

    def test_check_health_status_values_are_valid(self, service, mock_db, mock_worker):
        """check_health의 status가 유효한 값"""
        # No worker
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = service.check_health()
        assert result["status"] in ["healthy", "warning", "dead", "no_worker"]

        # With worker
        mock_worker.last_heartbeat = datetime.now()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_worker
        result = service.check_health()
        assert result["status"] in ["healthy", "warning", "dead", "no_worker"]


# ============================================================
# 마이그레이션 테스트
# ============================================================

class TestMigration032:
    """032_instagram_worker_status.sql 마이그레이션 테스트"""

    def test_migration_032_exists(self):
        """032_instagram_worker_status.sql 파일 존재"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "032_instagram_worker_status.sql"
        assert migration_path.exists(), "032_instagram_worker_status.sql should exist"

    def test_migration_032_contains_table(self):
        """032 마이그레이션에 instagram_worker_status 테이블 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "032_instagram_worker_status.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "instagram_worker_status" in content
        assert "worker_id" in content
        assert "pid" in content
        assert "last_heartbeat" in content
        assert "current_state" in content


# ============================================================
# 모델 테스트
# ============================================================

class TestInstagramWorkerStatusModel:
    """InstagramWorkerStatus 모델 테스트"""

    def test_model_exists(self):
        """InstagramWorkerStatus 모델 존재"""
        from app.models import InstagramWorkerStatus

        assert InstagramWorkerStatus is not None

    def test_model_has_required_columns(self):
        """InstagramWorkerStatus 모델에 필수 컬럼 존재"""
        from app.models import InstagramWorkerStatus

        required_columns = [
            "id", "worker_id", "pid", "started_at", "last_heartbeat",
            "current_state", "current_account", "current_run_id", "is_alive"
        ]

        for col in required_columns:
            assert hasattr(InstagramWorkerStatus, col), f"Missing column: {col}"


# ============================================================
# 스키마 테스트
# ============================================================

class TestWorkerStatusSchemas:
    """워커 상태 스키마 테스트"""

    def test_worker_status_schema_exists(self):
        """WorkerStatusSchema 존재"""
        from app.modules.instagram.models.schemas import WorkerStatusSchema

        assert WorkerStatusSchema is not None

    def test_worker_health_schema_exists(self):
        """WorkerHealthSchema 존재"""
        from app.modules.instagram.models.schemas import WorkerHealthSchema

        assert WorkerHealthSchema is not None

    def test_worker_status_schema_has_computed_fields(self):
        """WorkerStatusSchema에 계산 필드 존재"""
        from app.modules.instagram.models.schemas import WorkerStatusSchema

        fields = WorkerStatusSchema.model_fields
        assert "uptime_seconds" in fields
        assert "heartbeat_age_seconds" in fields

    def test_worker_health_schema_has_required_fields(self):
        """WorkerHealthSchema에 필수 필드 존재"""
        from app.modules.instagram.models.schemas import WorkerHealthSchema

        fields = WorkerHealthSchema.model_fields
        required = ["status", "worker_id", "last_heartbeat",
                   "heartbeat_age_seconds", "current_state", "message"]
        for field in required:
            assert field in fields, f"Missing field: {field}"


# ============================================================
# 상수 테스트
# ============================================================

class TestConstants:
    """상수값 테스트"""

    def test_healthy_threshold_value(self):
        """HEALTHY_THRESHOLD가 60초"""
        assert HEALTHY_THRESHOLD == 60

    def test_warning_threshold_value(self):
        """WARNING_THRESHOLD가 120초"""
        assert WARNING_THRESHOLD == 120

    def test_warning_threshold_greater_than_healthy(self):
        """WARNING_THRESHOLD > HEALTHY_THRESHOLD"""
        assert WARNING_THRESHOLD > HEALTHY_THRESHOLD
