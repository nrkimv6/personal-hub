"""
일별 통계 서비스 단위 테스트
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.daily_stats import ProxyDailyStats, MonitoringDailyStats
from app.models.proxy_usage import ProxyUsageLog
from app.models.monitoring_event import MonitoringEvent
from app.models.monitor_schedule import MonitorSchedule
from app.models.biz_item import BizItem
from app.models.business import Business
from app.services.daily_stats_service import DailyStatsService, daily_stats_service
from app.schemas.daily_stats import ProxyDailyStatsListParams, MonitoringDailyStatsListParams


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
def sample_proxy_usage_logs(test_db):
    """테스트용 프록시 사용 로그 생성"""
    # 먼저 스케줄과 관련 데이터 생성
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

    schedule = MonitorSchedule(
        biz_item_id=biz_item.id,
        date="2025-12-20",
        is_active=False,
        is_enabled=True
    )
    test_db.add(schedule)
    test_db.commit()

    # 어제 날짜 데이터
    yesterday = date.today() - timedelta(days=1)
    yesterday_start = datetime.combine(yesterday, datetime.min.time())

    logs = []
    # 프록시 A: 10회 성공, 5회 실패
    for i in range(10):
        logs.append(ProxyUsageLog(
            schedule_id=schedule.id,
            proxy_url="http://1.1.1.1:8080",
            proxy_host="1.1.1.1",
            attempt_number=1,
            success=1,
            response_time_ms=100 + i * 10,
            timestamp=yesterday_start + timedelta(hours=i),
        ))
    for i in range(5):
        logs.append(ProxyUsageLog(
            schedule_id=schedule.id,
            proxy_url="http://1.1.1.1:8080",
            proxy_host="1.1.1.1",
            attempt_number=1,
            success=0,
            error_type="timeout",
            timestamp=yesterday_start + timedelta(hours=10 + i),
        ))

    # 프록시 B: 3회 성공
    for i in range(3):
        logs.append(ProxyUsageLog(
            schedule_id=schedule.id,
            proxy_url="http://2.2.2.2:8080",
            proxy_host="2.2.2.2",
            attempt_number=1,
            success=1,
            response_time_ms=200,
            timestamp=yesterday_start + timedelta(hours=i),
        ))

    test_db.add_all(logs)
    test_db.commit()

    return {"schedule": schedule, "logs": logs, "yesterday": yesterday}


@pytest.fixture
def sample_monitoring_events(test_db, sample_proxy_usage_logs):
    """테스트용 모니터링 이벤트 생성"""
    schedule = sample_proxy_usage_logs["schedule"]
    yesterday = sample_proxy_usage_logs["yesterday"]
    yesterday_start = datetime.combine(yesterday, datetime.min.time())

    events = []
    # 성공 5건
    for i in range(5):
        events.append(MonitoringEvent(
            schedule_id=schedule.id,
            timestamp=yesterday_start + timedelta(hours=i),
            event_type="check",
            status="success",
            response_time_ms=100 + i * 10,
        ))

    # 에러 2건
    for i in range(2):
        events.append(MonitoringEvent(
            schedule_id=schedule.id,
            timestamp=yesterday_start + timedelta(hours=5 + i),
            event_type="check",
            status="error",
            error_message="Connection timeout",
        ))

    # available 1건 (예약 트리거)
    events.append(MonitoringEvent(
        schedule_id=schedule.id,
        timestamp=yesterday_start + timedelta(hours=8),
        event_type="slot_detected",
        status="available",
        available_count=3,
        booking_triggered=True,
        booking_success=True,
    ))

    test_db.add_all(events)
    test_db.commit()

    return {"schedule": schedule, "events": events, "yesterday": yesterday}


class TestDailyStatsService:
    """DailyStatsService 테스트"""

    def test_aggregate_proxy_daily_stats_success(self, test_db, sample_proxy_usage_logs):
        """프록시 일별 통계 집계 - 성공"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        count = service.aggregate_proxy_daily_stats(test_db, yesterday)

        # 2개 프록시 (1.1.1.1, 2.2.2.2)
        assert count == 2

        # 집계 결과 확인
        stats = test_db.query(ProxyDailyStats).filter(
            ProxyDailyStats.date == yesterday
        ).all()

        assert len(stats) == 2

        # 프록시 A 검증
        proxy_a = next(s for s in stats if s.proxy_host == "1.1.1.1")
        assert proxy_a.total_attempts == 15
        assert proxy_a.success_count == 10
        assert proxy_a.fail_count == 5
        assert proxy_a.avg_response_time_ms is not None

        # 에러 유형 검증
        error_types = json.loads(proxy_a.error_types)
        assert error_types.get("timeout") == 5

        # 프록시 B 검증
        proxy_b = next(s for s in stats if s.proxy_host == "2.2.2.2")
        assert proxy_b.total_attempts == 3
        assert proxy_b.success_count == 3
        assert proxy_b.fail_count == 0

    def test_aggregate_proxy_daily_stats_skip_existing(self, test_db, sample_proxy_usage_logs):
        """이미 집계된 날짜는 스킵"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        # 첫 번째 집계
        count1 = service.aggregate_proxy_daily_stats(test_db, yesterday)
        assert count1 == 2

        # 두 번째 집계 시도 - 스킵됨
        count2 = service.aggregate_proxy_daily_stats(test_db, yesterday, force=False)
        assert count2 == 0

    def test_aggregate_proxy_daily_stats_force_overwrite(self, test_db, sample_proxy_usage_logs):
        """force=True면 기존 데이터 덮어쓰기"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        # 첫 번째 집계
        count1 = service.aggregate_proxy_daily_stats(test_db, yesterday)
        assert count1 == 2

        # 강제 재집계
        count2 = service.aggregate_proxy_daily_stats(test_db, yesterday, force=True)
        assert count2 == 2

        # 중복 없이 2개만 존재해야 함
        total = test_db.query(ProxyDailyStats).filter(
            ProxyDailyStats.date == yesterday
        ).count()
        assert total == 2

    def test_aggregate_proxy_daily_stats_no_data(self, test_db):
        """데이터가 없으면 0 반환"""
        service = DailyStatsService()
        yesterday = date.today() - timedelta(days=1)

        count = service.aggregate_proxy_daily_stats(test_db, yesterday)
        assert count == 0

    def test_aggregate_monitoring_daily_stats_success(self, test_db, sample_monitoring_events):
        """모니터링 일별 통계 집계 - 성공"""
        service = DailyStatsService()
        yesterday = sample_monitoring_events["yesterday"]

        count = service.aggregate_monitoring_daily_stats(test_db, yesterday)

        # 1개 스케줄
        assert count == 1

        # 집계 결과 확인
        stats = test_db.query(MonitoringDailyStats).filter(
            MonitoringDailyStats.date == yesterday
        ).first()

        assert stats is not None
        assert stats.check_count == 8  # 5 성공 + 2 에러 + 1 available
        assert stats.success_count == 5
        assert stats.error_count == 2
        assert stats.available_detected == 1
        assert stats.booking_triggered == 1
        assert stats.booking_success == 1

    def test_aggregate_monitoring_daily_stats_skip_existing(self, test_db, sample_monitoring_events):
        """이미 집계된 날짜는 스킵"""
        service = DailyStatsService()
        yesterday = sample_monitoring_events["yesterday"]

        count1 = service.aggregate_monitoring_daily_stats(test_db, yesterday)
        assert count1 == 1

        count2 = service.aggregate_monitoring_daily_stats(test_db, yesterday, force=False)
        assert count2 == 0

    def test_aggregate_date_range(self, test_db, sample_proxy_usage_logs):
        """날짜 범위 집계"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        # 단일 날짜 범위
        proxy_count, monitoring_count = service.aggregate_date_range(
            test_db, yesterday, yesterday
        )

        assert proxy_count == 2
        # 모니터링 이벤트가 없으므로 0
        assert monitoring_count == 0

    def test_get_proxy_daily_stats(self, test_db, sample_proxy_usage_logs):
        """프록시 일별 통계 조회"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        # 먼저 집계
        service.aggregate_proxy_daily_stats(test_db, yesterday)

        # 조회
        params = ProxyDailyStatsListParams(date_from=yesterday, date_to=yesterday)
        stats = service.get_proxy_daily_stats(test_db, params)

        assert len(stats) == 2

    def test_get_proxy_daily_stats_filter_by_host(self, test_db, sample_proxy_usage_logs):
        """프록시 호스트로 필터링"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        service.aggregate_proxy_daily_stats(test_db, yesterday)

        params = ProxyDailyStatsListParams(proxy_host="1.1.1.1")
        stats = service.get_proxy_daily_stats(test_db, params)

        assert len(stats) == 1
        assert stats[0].proxy_host == "1.1.1.1"

    def test_get_stats_summary(self, test_db, sample_proxy_usage_logs, sample_monitoring_events):
        """통계 요약 조회"""
        service = DailyStatsService()
        yesterday = sample_proxy_usage_logs["yesterday"]

        # 집계
        service.aggregate_proxy_daily_stats(test_db, yesterday)
        service.aggregate_monitoring_daily_stats(test_db, yesterday)

        # 요약 조회
        summary = service.get_stats_summary(test_db)

        assert summary["proxy_daily_stats"]["count"] == 2
        assert summary["proxy_daily_stats"]["oldest_date"] == yesterday
        assert summary["monitoring_daily_stats"]["count"] == 1


class TestDailyStatsServiceEdgeCases:
    """에지 케이스 테스트"""

    def test_aggregate_with_null_proxy_host(self, test_db):
        """proxy_host가 NULL인 로그는 무시"""
        # 스케줄 생성
        business = Business(name="Test", business_id="123")
        test_db.add(business)
        test_db.commit()

        biz_item = BizItem(name="Test", business_id=business.id, biz_item_id="456")
        test_db.add(biz_item)
        test_db.commit()

        schedule = MonitorSchedule(biz_item_id=biz_item.id, date="2025-12-20", is_active=False, is_enabled=True)
        test_db.add(schedule)
        test_db.commit()

        yesterday = date.today() - timedelta(days=1)
        yesterday_start = datetime.combine(yesterday, datetime.min.time())

        # proxy_host가 NULL인 로그
        log = ProxyUsageLog(
            schedule_id=schedule.id,
            proxy_url="http://example.com",
            proxy_host=None,
            attempt_number=1,
            success=1,
            timestamp=yesterday_start,
        )
        test_db.add(log)
        test_db.commit()

        service = DailyStatsService()
        count = service.aggregate_proxy_daily_stats(test_db, yesterday)

        # NULL 호스트는 집계에서 제외
        assert count == 0

    def test_aggregate_future_date(self, test_db):
        """미래 날짜는 데이터 없음"""
        service = DailyStatsService()
        future = date.today() + timedelta(days=1)

        count = service.aggregate_proxy_daily_stats(test_db, future)
        assert count == 0

    def test_default_target_date_is_yesterday(self, test_db, sample_proxy_usage_logs):
        """target_date 미지정 시 어제 날짜 사용"""
        service = DailyStatsService()

        # target_date 미지정
        count = service.aggregate_proxy_daily_stats(test_db)

        # 어제 데이터가 있으므로 집계됨
        assert count == 2
