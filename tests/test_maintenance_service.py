"""
유지보수 서비스 단위 테스트
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.daily_stats import ProxyDailyStats, MonitoringDailyStats, MaintenanceRun
from app.models.proxy_usage import ProxyUsageLog
from app.models.monitoring_event import MonitoringEvent
from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.services.maintenance_service import MaintenanceService, maintenance_service
from app.schemas.daily_stats import CleanupParams


@pytest.fixture
def test_db():
    """테스트용 인메모리 SQLite DB"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_data(test_db):
    """테스트용 샘플 데이터 생성"""
    # Business, BizItem, Schedule 생성
    business = Business(name="Test Business", business_id="123")
    test_db.add(business)
    test_db.commit()

    biz_item = BizItem(
        name="Test Item",
        business_id=business.id,
        biz_item_id="456"
    )
    test_db.add(biz_item)
    test_db.commit()

    # 활성 스케줄
    active_schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        date="2025-12-20",
        is_active=True,
        is_enabled=True
    )
    # 비활성 스케줄
    inactive_schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        date="2025-12-21",
        is_active=False,
        is_enabled=False
    )
    test_db.add_all([active_schedule, inactive_schedule])
    test_db.commit()

    yesterday = date.today() - timedelta(days=1)
    old_date = date.today() - timedelta(days=60)

    # 어제 데이터
    yesterday_start = datetime.combine(yesterday, datetime.min.time())
    for i in range(5):
        test_db.add(ProxyUsageLog(
            schedule_id=active_schedule.id,
            proxy_url="http://1.1.1.1:8080",
            proxy_host="1.1.1.1",
            attempt_number=1,
            success=1,
            response_time_ms=100,
            timestamp=yesterday_start + timedelta(hours=i),
        ))
        test_db.add(MonitoringEvent(
            schedule_id=active_schedule.id,
            timestamp=yesterday_start + timedelta(hours=i),
            event_type="check",
            status="success",
        ))

    # 60일 전 데이터 (정리 대상)
    old_start = datetime.combine(old_date, datetime.min.time())
    for i in range(10):
        test_db.add(ProxyUsageLog(
            schedule_id=active_schedule.id,
            proxy_url="http://2.2.2.2:8080",
            proxy_host="2.2.2.2",
            attempt_number=1,
            success=0,
            error_type="timeout",
            timestamp=old_start + timedelta(hours=i),
        ))
        # 비활성 스케줄의 오래된 이벤트 (정리 대상)
        test_db.add(MonitoringEvent(
            schedule_id=inactive_schedule.id,
            timestamp=old_start + timedelta(hours=i),
            event_type="check",
            status="error",
        ))

    test_db.commit()

    return {
        "active_schedule": active_schedule,
        "inactive_schedule": inactive_schedule,
        "yesterday": yesterday,
        "old_date": old_date,
    }


class TestMaintenanceService:
    """MaintenanceService 테스트"""

    def test_run_daily_maintenance_success(self, test_db, sample_data):
        """일별 유지보수 성공"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        cleanup_params = CleanupParams(
            proxy_usage_days=30,
            monitoring_events_days=30,
            dry_run=False,
        )

        result = service.run_daily_maintenance(
            test_db,
            target_date=yesterday,
            cleanup_params=cleanup_params,
            run_vacuum=False,  # 테스트에서는 VACUUM 스킵
        )

        assert result.success is True
        assert result.proxy_stats_aggregated >= 1
        # 60일 전 데이터 10건 삭제됨
        assert result.proxy_usage_logs_deleted == 10
        # 비활성 스케줄의 60일 전 이벤트 10건 삭제됨
        assert result.monitoring_events_deleted == 10

    def test_run_daily_maintenance_dry_run(self, test_db, sample_data):
        """dry_run 모드에서는 삭제 안 함"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        cleanup_params = CleanupParams(dry_run=True)

        result = service.run_daily_maintenance(
            test_db,
            target_date=yesterday,
            cleanup_params=cleanup_params,
            run_vacuum=False,
        )

        assert result.success is True
        # 집계는 수행됨
        assert result.proxy_stats_aggregated >= 1
        # 삭제는 안 됨
        assert result.proxy_usage_logs_deleted == 0
        assert result.monitoring_events_deleted == 0

    def test_run_daily_maintenance_already_completed(self, test_db, sample_data):
        """이미 완료된 날짜는 스킵"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        cleanup_params = CleanupParams(dry_run=True)

        # 첫 번째 실행
        result1 = service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )
        assert result1.success is True

        # 두 번째 실행 - 이미 완료됨
        result2 = service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )
        assert result2.success is True
        assert result2.error_message == "Already completed"

    def test_run_daily_maintenance_creates_run_record(self, test_db, sample_data):
        """유지보수 실행 기록 생성"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        cleanup_params = CleanupParams(dry_run=True)
        result = service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )

        # MaintenanceRun 레코드 확인
        run = test_db.query(MaintenanceRun).filter(
            MaintenanceRun.run_date == yesterday
        ).first()

        assert run is not None
        assert run.status == "success"
        assert run.proxy_stats_aggregated >= 1

    def test_get_maintenance_stats(self, test_db, sample_data):
        """유지보수 상태 조회"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        # 유지보수 실행
        cleanup_params = CleanupParams(dry_run=True)
        service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )

        # 상태 조회
        stats = service.get_maintenance_stats(test_db)

        # 어제 데이터 5건 + 60일 전 데이터 10건 = 15건 (dry_run이므로 삭제 안 됨)
        assert stats.proxy_usage_logs_count == 15
        # 마지막 유지보수 정보
        assert stats.last_maintenance_run is not None
        assert stats.last_maintenance_run.status == "success"

    def test_get_maintenance_runs(self, test_db, sample_data):
        """유지보수 실행 이력 조회"""
        service = MaintenanceService()

        # 여러 날짜 유지보수 실행
        for days_ago in [1, 2, 3]:
            target = date.today() - timedelta(days=days_ago)
            cleanup_params = CleanupParams(dry_run=True)
            service.run_daily_maintenance(
                test_db, target_date=target, cleanup_params=cleanup_params, run_vacuum=False
            )

        runs = service.get_maintenance_runs(test_db, limit=10)

        assert len(runs) == 3
        # 최신순 정렬
        assert runs[0].run_date > runs[1].run_date

    def test_backfill_daily_stats(self, test_db, sample_data):
        """과거 날짜 백필"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        result = service.backfill_daily_stats(
            test_db,
            start_date=yesterday,
            end_date=yesterday,
        )

        assert result["proxy"] >= 1
        # 어제 날짜에 모니터링 이벤트가 있으므로
        assert result["monitoring"] >= 1


class TestMaintenanceServiceCleanup:
    """정리 기능 테스트"""

    def test_cleanup_respects_retention_days(self, test_db, sample_data):
        """보존 기간 설정 준수"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        # 90일 보존 설정 - 60일 전 데이터는 유지됨
        cleanup_params = CleanupParams(
            proxy_usage_days=90,
            monitoring_events_days=90,
            dry_run=False,
        )

        result = service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )

        # 60일 전 데이터는 90일 이내이므로 삭제 안 됨
        assert result.proxy_usage_logs_deleted == 0

    def test_cleanup_only_inactive_schedule_events(self, test_db, sample_data):
        """비활성 스케줄의 이벤트만 정리"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]
        active_schedule = sample_data["active_schedule"]

        # 활성 스케줄의 오래된 이벤트 추가
        old_date = date.today() - timedelta(days=60)
        old_start = datetime.combine(old_date, datetime.min.time())

        for i in range(5):
            test_db.add(MonitoringEvent(
                schedule_id=active_schedule.id,
                timestamp=old_start + timedelta(hours=i),
                event_type="check",
                status="success",
            ))
        test_db.commit()

        cleanup_params = CleanupParams(
            proxy_usage_days=30,
            monitoring_events_days=30,
            dry_run=False,
        )

        result = service.run_daily_maintenance(
            test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
        )

        # 비활성 스케줄의 10건만 삭제됨 (활성 스케줄의 5건은 유지)
        assert result.monitoring_events_deleted == 10

        # 활성 스케줄의 이벤트는 남아있음
        active_events = test_db.query(MonitoringEvent).filter(
            MonitoringEvent.schedule_id == active_schedule.id
        ).count()
        # 어제 5건 + 60일 전 5건 = 10건
        assert active_events == 10


class TestMaintenanceServiceErrorHandling:
    """에러 처리 테스트"""

    def test_run_daily_maintenance_handles_error(self, test_db, sample_data):
        """에러 발생 시 실패 기록"""
        service = MaintenanceService()
        yesterday = sample_data["yesterday"]

        # daily_stats_service를 모킹하여 에러 발생
        with patch.object(
            service,
            "_cleanup_old_logs",
            side_effect=Exception("Test error")
        ):
            cleanup_params = CleanupParams(dry_run=False)
            result = service.run_daily_maintenance(
                test_db, target_date=yesterday, cleanup_params=cleanup_params, run_vacuum=False
            )

        assert result.success is False
        assert "Test error" in result.error_message

        # 실패 기록 확인
        run = test_db.query(MaintenanceRun).filter(
            MaintenanceRun.run_date == yesterday
        ).first()
        assert run.status == "failed"
