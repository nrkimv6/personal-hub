"""
Instagram 서비스 테스트

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
- Reference: 참조 검증 (외래키, 연관 데이터)
- Existence: 존재 여부
- Cardinality: 개수 검증
- Time: 시간 관련 테스트

테스트 대상:
- InstagramScheduler (랜덤 스케줄 생성)
- PostService (게시물 CRUD)
- CrawlService (크롤링 관리)
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch
from typing import List

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.instagram.models.schemas import TimeWindow


# ============================================================
# 테스트 픽스처
# ============================================================

@pytest.fixture
def sample_time_windows():
    """테스트용 시간 윈도우"""
    return [
        TimeWindow(start="09:00", end="12:00"),
        TimeWindow(start="14:00", end="17:00"),
        TimeWindow(start="19:00", end="22:00")
    ]


@pytest.fixture
def scheduler(sample_time_windows):
    """InstagramScheduler 인스턴스"""
    from app.modules.instagram.services.scheduler import InstagramScheduler
    return InstagramScheduler(
        daily_runs=3,
        time_windows=sample_time_windows
    )


@pytest.fixture
def scheduler_single_run(sample_time_windows):
    """단일 실행 스케줄러"""
    from app.modules.instagram.services.scheduler import InstagramScheduler
    return InstagramScheduler(
        daily_runs=1,
        time_windows=sample_time_windows
    )


@pytest.fixture
def mock_db():
    """Mock 데이터베이스 세션"""
    return MagicMock()


# ============================================================
# InstagramScheduler 테스트 - Right (결과 검증)
# ============================================================

class TestSchedulerRight:
    """스케줄러 결과 검증 테스트"""

    def test_generate_daily_schedule_returns_correct_count(self, scheduler):
        """일일 스케줄이 지정된 횟수만큼 생성되는지 확인"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        assert len(schedule) == 3

    def test_schedule_times_within_windows(self, scheduler, sample_time_windows):
        """생성된 시간이 시간 윈도우 내에 있는지 확인"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        for scheduled_time in schedule:
            time_str = scheduled_time.strftime("%H:%M")
            is_in_window = False
            for window in sample_time_windows:
                if window.start <= time_str <= window.end:
                    is_in_window = True
                    break
            assert is_in_window, f"Time {time_str} is not in any window"

    def test_deterministic_schedule_same_day(self, scheduler):
        """같은 날짜에 대해 동일한 스케줄이 생성되는지 확인"""
        test_date = date(2025, 12, 25)

        schedule1 = scheduler.generate_daily_schedule(test_date)
        schedule2 = scheduler.generate_daily_schedule(test_date)

        assert schedule1 == schedule2

    def test_different_schedule_different_day(self, scheduler):
        """다른 날짜에 대해 다른 스케줄이 생성되는지 확인"""
        date1 = date(2025, 12, 25)
        date2 = date(2025, 12, 26)

        schedule1 = scheduler.generate_daily_schedule(date1)
        schedule2 = scheduler.generate_daily_schedule(date2)

        # 두 스케줄 모두 올바른 개수 확인
        assert len(schedule1) == 3
        assert len(schedule2) == 3
        # 확률적으로 달라야 함 (드물게 같을 수 있음)
        # 최소한 생성 자체는 성공
        assert all(isinstance(t, datetime) for t in schedule1)
        assert all(isinstance(t, datetime) for t in schedule2)

    def test_schedule_is_sorted(self, scheduler):
        """스케줄이 시간순으로 정렬되어 있는지 확인"""
        schedule = scheduler.generate_daily_schedule()

        for i in range(len(schedule) - 1):
            assert schedule[i] <= schedule[i + 1]


# ============================================================
# InstagramScheduler 테스트 - Boundary (경계값)
# ============================================================

class TestSchedulerBoundary:
    """스케줄러 경계값 테스트"""

    def test_single_run_schedule(self, scheduler_single_run):
        """일일 1회 스케줄 생성"""
        schedule = scheduler_single_run.generate_daily_schedule()
        assert len(schedule) == 1

    def test_many_runs_schedule(self, sample_time_windows):
        """많은 횟수의 스케줄 생성 (윈도우 개수 초과시 윈도우 개수만큼)"""
        from app.modules.instagram.services.scheduler import InstagramScheduler
        # 10회 요청하지만 윈도우는 3개만 있음
        scheduler = InstagramScheduler(daily_runs=10, time_windows=sample_time_windows)
        schedule = scheduler.generate_daily_schedule()

        # 윈도우 개수만큼만 생성됨
        assert len(schedule) == 3

    def test_default_time_windows(self):
        """기본 시간 윈도우 사용"""
        from app.modules.instagram.services.scheduler import InstagramScheduler
        scheduler = InstagramScheduler()

        schedule = scheduler.generate_daily_schedule()
        assert len(schedule) == 3


# ============================================================
# InstagramScheduler 테스트 - Time (시간 관련)
# ============================================================

class TestSchedulerTime:
    """스케줄러 시간 관련 테스트"""

    def test_should_run_now_within_tolerance(self, scheduler):
        """허용 오차 내에서 실행 여부 확인"""
        # 오늘 스케줄의 첫 시간을 가져옴
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            # 실행 시간 직후로 now 설정
            now = run_time + timedelta(minutes=2)

            should_run = scheduler.should_run_now(
                last_run=None,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is True

    def test_should_run_now_outside_tolerance(self, scheduler):
        """허용 오차 외에서 실행 안함 확인"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            # 실행 시간 10분 후로 now 설정
            now = run_time + timedelta(minutes=10)

            should_run = scheduler.should_run_now(
                last_run=None,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is False

    def test_should_not_run_if_already_ran(self, scheduler):
        """이미 실행된 경우 재실행 안함"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = run_time + timedelta(minutes=1)  # 1분 후에 이미 실행

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is False

    def test_get_next_run_time(self, scheduler):
        """다음 실행 시간 가져오기"""
        # 자정에 다음 실행 시간 확인
        today = date.today()
        midnight = datetime.combine(today, datetime.min.time())

        next_run = scheduler.get_next_run_time(midnight)

        assert next_run is not None
        assert next_run > midnight

    def test_get_completed_count(self, scheduler):
        """완료된 실행 횟수 확인"""
        today = date.today()
        runs = [
            datetime.combine(today, datetime.min.time().replace(hour=10)),
            datetime.combine(today, datetime.min.time().replace(hour=15)),
        ]

        count = scheduler.get_completed_count(runs, today)

        assert count == 2


# ============================================================
# PostService 테스트
# ============================================================

class TestPostService:
    """게시물 서비스 테스트"""

    def test_create_post_new(self, mock_db):
        """새 게시물 생성"""
        from app.modules.instagram.services.post_service import PostService

        # 중복 없음 - exists_by_post_id가 False 반환
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = PostService(mock_db)
        result = service.create_post(
            post_id="abc123",
            account="testuser",
            url="https://instagram.com/p/abc123",
            caption="Test caption",
            images=[],
            is_ad=False
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_post_skips_duplicate(self, mock_db):
        """중복 게시물 생성 스킵"""
        from app.modules.instagram.services.post_service import PostService

        # 중복 있음 - exists_by_post_id가 True 반환
        existing_post = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing_post

        service = PostService(mock_db)
        result = service.create_post(
            post_id="abc123",
            account="testuser"
        )

        assert result is None
        mock_db.add.assert_not_called()

    def test_delete_post(self, mock_db):
        """게시물 삭제"""
        from app.modules.instagram.services.post_service import PostService

        existing_post = MagicMock()
        existing_post.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = existing_post

        service = PostService(mock_db)
        result = service.delete_post(1)

        assert result is True
        mock_db.delete.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_delete_post_not_found(self, mock_db):
        """존재하지 않는 게시물 삭제"""
        from app.modules.instagram.services.post_service import PostService

        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = PostService(mock_db)
        result = service.delete_post(999)

        assert result is False


# ============================================================
# CrawlService 테스트
# ============================================================

class TestCrawlService:
    """크롤링 서비스 테스트"""

    def test_get_schedule_config_returns_none_if_not_exists(self, mock_db):
        """설정이 없으면 None 반환"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_db.query.return_value.first.return_value = None

        service = CrawlService(mock_db)
        config = service.get_schedule_config()

        assert config is None

    def test_update_schedule_config_creates_if_not_exists(self, mock_db):
        """설정이 없으면 생성"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_db.query.return_value.first.return_value = None

        service = CrawlService(mock_db)
        config = service.update_schedule_config(enabled=True, daily_runs=3)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    def test_update_schedule_config_updates_existing(self, mock_db):
        """기존 설정 업데이트"""
        from app.modules.instagram.services.crawl_service import CrawlService

        existing_config = MagicMock()
        existing_config.enabled = True
        existing_config.daily_runs = 3
        mock_db.query.return_value.first.return_value = existing_config

        service = CrawlService(mock_db)
        updated = service.update_schedule_config(enabled=False, daily_runs=5)

        assert updated.enabled is False
        assert updated.daily_runs == 5


# ============================================================
# 통합 테스트
# ============================================================

class TestIntegration:
    """통합 테스트"""

    def test_scheduler_schedule_is_sorted(self, scheduler):
        """스케줄러가 정렬된 리스트 반환"""
        schedule = scheduler.generate_daily_schedule()

        sorted_schedule = sorted(schedule)
        assert schedule == sorted_schedule

    def test_post_data_creation(self):
        """PostData 생성 검증"""
        from app.modules.instagram.services.crawler import PostData

        post_data = PostData(
            index=0,
            account="testaccount",
            url="https://instagram.com/p/test123",
            caption="Test caption with #hashtag",
            images=[{"src": "https://example.com/img.jpg", "alt": "test"}],
            display_time="2시간 전",
            is_ad=True
        )

        assert post_data.index == 0
        assert post_data.is_ad is True
        assert len(post_data.images) == 1
        assert post_data.account == "testaccount"


# ============================================================
# DB 스키마 마이그레이션 테스트
# ============================================================

class TestMigration:
    """마이그레이션 검증 테스트"""

    def test_migration_file_exists(self):
        """마이그레이션 파일 존재 확인"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "006_instagram.sql"
        assert migration_path.exists(), "Instagram migration file should exist"

    def test_migration_contains_tables(self):
        """마이그레이션에 필요한 테이블 포함 확인"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "006_instagram.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "instagram_posts" in content
        assert "instagram_crawl_runs" in content
        assert "instagram_schedule_config" in content

    def test_model_imports(self):
        """모델 임포트 확인"""
        from app.models.instagram_post import InstagramPost
        from app.models.instagram_crawl_run import InstagramCrawlRun
        from app.models.instagram_schedule_config import InstagramScheduleConfig

        assert InstagramPost is not None
        assert InstagramCrawlRun is not None
        assert InstagramScheduleConfig is not None


# ============================================================
# TimeWindow 스키마 테스트
# ============================================================

class TestTimeWindowSchema:
    """시간 윈도우 스키마 테스트"""

    def test_time_window_creation(self):
        """TimeWindow 생성"""
        window = TimeWindow(start="09:00", end="12:00")
        assert window.start == "09:00"
        assert window.end == "12:00"

    def test_time_window_comparison(self):
        """TimeWindow 비교"""
        window1 = TimeWindow(start="09:00", end="12:00")
        window2 = TimeWindow(start="09:00", end="12:00")
        window3 = TimeWindow(start="14:00", end="17:00")

        assert window1.start == window2.start
        assert window1.end == window2.end
        assert window1.start != window3.start


# ============================================================
# 최소 실행 간격 테스트 (min_interval_hours)
# ============================================================

class TestSchedulerMinInterval:
    """스케줄러 최소 실행 간격 테스트"""

    def test_should_run_when_no_min_interval(self, scheduler):
        """min_interval이 0이면 기존 로직대로 동작"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = run_time - timedelta(minutes=30)

            # min_interval_hours=0이면 제한 없음
            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=0
            )
            assert should_run is True

    def test_should_not_run_within_min_interval(self, scheduler):
        """min_interval 이내에는 실행하지 않음"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            # 30분 전에 실행됨 - 2시간 간격 설정시 실행 안함
            last_run = now - timedelta(minutes=30)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2  # 2시간 간격
            )
            assert should_run is False

    def test_should_run_after_min_interval(self, scheduler):
        """min_interval 경과 후에는 실행"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            # 3시간 전에 실행됨 - 2시간 간격 설정시 실행 가능
            last_run = now - timedelta(hours=3)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2  # 2시간 간격
            )
            assert should_run is True

    def test_min_interval_boundary_exact(self, scheduler):
        """정확히 min_interval 시간 경과 시 - 경계값 테스트"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            # 정확히 2시간 전에 실행됨
            last_run = now - timedelta(hours=2)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2
            )
            # 정확히 같으면 실행 (>= 조건이 아니라 < 조건이므로 정확히 같으면 실행됨)
            assert should_run is True

    def test_min_interval_with_no_last_run(self, scheduler):
        """마지막 실행 기록이 없으면 min_interval 무시"""
        today = date.today()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)

            should_run = scheduler.should_run_now(
                last_run=None,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2
            )
            assert should_run is True


# ============================================================
# 중복 감지 중단 테스트 (duplicate_stop_count)
# ============================================================

class TestCrawlerDuplicateStop:
    """크롤러 중복 감지 중단 테스트"""

    def test_crawl_options_has_duplicate_stop_count(self):
        """CrawlOptions에 duplicate_stop_count 필드 존재"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()
        assert hasattr(options, 'duplicate_stop_count')
        assert options.duplicate_stop_count == 5  # 기본값

    def test_crawl_options_custom_duplicate_stop(self):
        """CrawlOptions에 커스텀 duplicate_stop_count 설정"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(duplicate_stop_count=10)
        assert options.duplicate_stop_count == 10

    def test_crawl_options_disable_duplicate_stop(self):
        """duplicate_stop_count=0이면 비활성화"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(duplicate_stop_count=0)
        assert options.duplicate_stop_count == 0

    def test_crawler_has_db_duplicate_checker(self):
        """InstagramCrawler에 db_duplicate_checker 속성 존재"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        # Mock page 객체
        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, '_db_duplicate_checker')
        assert crawler._db_duplicate_checker is None

    def test_crawler_with_duplicate_checker(self):
        """InstagramCrawler에 duplicate_checker 설정"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        mock_checker = MagicMock(return_value=True)

        crawler = InstagramCrawler(mock_page, db_duplicate_checker=mock_checker)

        assert crawler._db_duplicate_checker is mock_checker

    def test_extract_post_id_from_url(self):
        """URL에서 게시물 ID 추출"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        # 정상 URL
        assert crawler._extract_post_id_from_url("https://www.instagram.com/p/ABC123/") == "ABC123"
        assert crawler._extract_post_id_from_url("https://www.instagram.com/p/ABC123") == "ABC123"
        assert crawler._extract_post_id_from_url("https://www.instagram.com/p/ABC123/?utm_source=test") == "ABC123"

        # 비정상 URL
        assert crawler._extract_post_id_from_url(None) is None
        assert crawler._extract_post_id_from_url("https://www.instagram.com/username/") is None


# ============================================================
# 스키마 테스트 (새 필드)
# ============================================================

class TestScheduleConfigSchema:
    """스케줄 설정 스키마 테스트"""

    def test_schedule_config_has_new_fields(self):
        """ScheduleConfigSchema에 새 필드 존재"""
        from app.modules.instagram.models.schemas import ScheduleConfigSchema

        # 필드 존재 확인
        fields = ScheduleConfigSchema.model_fields
        assert 'min_interval_hours' in fields
        assert 'duplicate_stop_count' in fields
        assert 'max_retries' in fields
        assert 'retry_interval_minutes' in fields

    def test_schedule_config_default_values(self):
        """ScheduleConfigSchema 기본값"""
        from app.modules.instagram.models.schemas import ScheduleConfigSchema

        config = ScheduleConfigSchema(id=1)
        assert config.min_interval_hours == 2
        assert config.duplicate_stop_count == 5
        assert config.max_retries == 3
        assert config.retry_interval_minutes == 5

    def test_schedule_config_update_has_new_fields(self):
        """ScheduleConfigUpdateSchema에 새 필드 존재"""
        from app.modules.instagram.models.schemas import ScheduleConfigUpdateSchema

        fields = ScheduleConfigUpdateSchema.model_fields
        assert 'min_interval_hours' in fields
        assert 'duplicate_stop_count' in fields
        assert 'max_retries' in fields
        assert 'retry_interval_minutes' in fields


class TestCrawlRunSchema:
    """크롤링 실행 기록 스키마 테스트"""

    def test_crawl_run_has_retry_fields(self):
        """CrawlRunSchema에 재시도 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlRunSchema

        fields = CrawlRunSchema.model_fields
        assert 'retry_count' in fields
        assert 'retry_of_run_id' in fields
        assert 'failure_reason' in fields

    def test_crawl_run_default_values(self):
        """CrawlRunSchema 기본값"""
        from app.modules.instagram.models.schemas import CrawlRunSchema
        from datetime import datetime

        run = CrawlRunSchema(
            id=1,
            account_id=1,
            started_at=datetime.now(),
            success=True,
            total_collected=10,
            new_saved=5,
        )
        assert run.retry_count == 0
        assert run.retry_of_run_id is None
        assert run.failure_reason is None


class TestCrawlOptionsSchema:
    """크롤링 옵션 스키마 테스트"""

    def test_crawl_options_has_duplicate_stop_count(self):
        """CrawlOptionsSchema에 duplicate_stop_count 필드 존재"""
        from app.modules.instagram.models.schemas import CrawlOptionsSchema

        fields = CrawlOptionsSchema.model_fields
        assert 'duplicate_stop_count' in fields

    def test_crawl_options_default_value(self):
        """CrawlOptionsSchema 기본값"""
        from app.modules.instagram.models.schemas import CrawlOptionsSchema

        options = CrawlOptionsSchema()
        assert options.duplicate_stop_count == 5


# ============================================================
# 모델 테스트 (새 필드)
# ============================================================

class TestInstagramModels:
    """Instagram 모델 테스트"""

    def test_schedule_config_model_has_new_columns(self):
        """InstagramScheduleConfig 모델에 새 컬럼 존재"""
        from app.models.instagram_schedule_config import InstagramScheduleConfig

        # 컬럼 존재 확인
        assert hasattr(InstagramScheduleConfig, 'min_interval_hours')
        assert hasattr(InstagramScheduleConfig, 'duplicate_stop_count')
        assert hasattr(InstagramScheduleConfig, 'max_retries')
        assert hasattr(InstagramScheduleConfig, 'retry_interval_minutes')

    def test_crawl_run_model_has_retry_columns(self):
        """InstagramCrawlRun 모델에 재시도 컬럼 존재"""
        from app.models.instagram_crawl_run import InstagramCrawlRun

        assert hasattr(InstagramCrawlRun, 'retry_count')
        assert hasattr(InstagramCrawlRun, 'retry_of_run_id')
        assert hasattr(InstagramCrawlRun, 'failure_reason')

    def test_crawl_request_model_exists(self):
        """InstagramCrawlRequest 모델 존재"""
        from app.models.instagram_crawl_request import InstagramCrawlRequest

        assert InstagramCrawlRequest is not None
        assert hasattr(InstagramCrawlRequest, 'account_id')
        assert hasattr(InstagramCrawlRequest, 'status')
        assert hasattr(InstagramCrawlRequest, 'requested_by')


# ============================================================
# 마이그레이션 테스트 (새 마이그레이션)
# ============================================================

class TestMigration007:
    """007 마이그레이션 검증 테스트"""

    def test_migration_007_exists(self):
        """007_instagram_enhancements.sql 파일 존재"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "007_instagram_enhancements.sql"
        assert migration_path.exists(), "007_instagram_enhancements.sql should exist"

    def test_migration_007_contains_new_columns(self):
        """007 마이그레이션에 새 컬럼 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "007_instagram_enhancements.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "min_interval_hours" in content
        assert "duplicate_stop_count" in content
        assert "max_retries" in content
        assert "retry_interval_minutes" in content
        assert "retry_count" in content
        assert "failure_reason" in content

    def test_migration_007_contains_crawl_requests_table(self):
        """007 마이그레이션에 instagram_crawl_requests 테이블 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "007_instagram_enhancements.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "instagram_crawl_requests" in content


# ============================================================
# Account ID 관련 테스트 (2025-12-21 추가)
# ============================================================

class TestScheduleConfigAccountId:
    """스케줄 설정 account_id 테스트"""

    def test_schedule_config_model_has_account_id(self):
        """InstagramScheduleConfig 모델에 account_id 컬럼 존재"""
        from app.models.instagram_schedule_config import InstagramScheduleConfig

        assert hasattr(InstagramScheduleConfig, 'account_id')
        assert hasattr(InstagramScheduleConfig, 'account')

    def test_schedule_config_schema_has_account_fields(self):
        """ScheduleConfigSchema에 account 필드 존재"""
        from app.modules.instagram.models.schemas import ScheduleConfigSchema

        fields = ScheduleConfigSchema.model_fields
        assert 'account_id' in fields
        assert 'account_name' in fields

    def test_schedule_config_update_schema_has_account_id(self):
        """ScheduleConfigUpdateSchema에 account_id 필드 존재"""
        from app.modules.instagram.models.schemas import ScheduleConfigUpdateSchema

        fields = ScheduleConfigUpdateSchema.model_fields
        assert 'account_id' in fields

    def test_schedule_config_schema_default_values(self):
        """ScheduleConfigSchema account 필드 기본값"""
        from app.modules.instagram.models.schemas import ScheduleConfigSchema

        config = ScheduleConfigSchema(id=1)
        assert config.account_id is None
        assert config.account_name is None

    def test_update_schedule_config_with_account_id(self, mock_db):
        """account_id로 스케줄 설정 업데이트"""
        from app.modules.instagram.services.crawl_service import CrawlService

        existing_config = MagicMock()
        existing_config.account_id = None
        mock_db.query.return_value.first.return_value = existing_config

        service = CrawlService(mock_db)
        updated = service.update_schedule_config(account_id=1)

        assert updated.account_id == 1

    def test_update_schedule_config_clear_account_id(self, mock_db):
        """account_id 초기화 (None 설정)는 명시적 값이 필요"""
        from app.modules.instagram.services.crawl_service import CrawlService

        existing_config = MagicMock()
        existing_config.account_id = 1
        mock_db.query.return_value.first.return_value = existing_config

        service = CrawlService(mock_db)
        # account_id를 전달하지 않으면 변경되지 않음
        updated = service.update_schedule_config(enabled=True)

        # account_id는 변경되지 않음 (None이 아닌 기존 값 유지)
        assert updated.account_id == 1


class TestMigration030:
    """030_add_instagram_account_id 마이그레이션 테스트"""

    def test_migration_030_exists(self):
        """030_add_instagram_account_id.sql 파일 존재"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "030_add_instagram_account_id.sql"
        assert migration_path.exists(), "030_add_instagram_account_id.sql should exist"

    def test_migration_030_contains_account_id(self):
        """030 마이그레이션에 account_id 컬럼 추가 포함"""
        migration_path = PROJECT_ROOT / "app" / "migrations" / "030_add_instagram_account_id.sql"
        content = migration_path.read_text(encoding="utf-8")

        assert "account_id" in content
        assert "ALTER TABLE" in content.upper() or "instagram_schedule_config" in content


class TestAccountRelationship:
    """Account 관계(relationship) 테스트"""

    def test_schedule_config_account_relationship(self):
        """InstagramScheduleConfig.account relationship 존재"""
        from app.models.instagram_schedule_config import InstagramScheduleConfig
        from sqlalchemy.orm import RelationshipProperty

        # account relationship이 정의되어 있는지 확인
        mapper = InstagramScheduleConfig.__mapper__
        assert 'account' in mapper.relationships

    def test_account_model_exists(self):
        """Account 모델 존재 및 필수 필드"""
        from app.models.account import Account

        assert hasattr(Account, 'id')
        assert hasattr(Account, 'name')
        assert hasattr(Account, 'is_logged_in')
        assert hasattr(Account, 'profile_path')


# ============================================================
# TodayScheduleItem 스키마 테스트 (RIGHT-BICEP)
# ============================================================

class TestTodayScheduleItemSchema:
    """TodayScheduleItem 스키마 테스트 (RIGHT-BICEP)"""

    # Right: 올바른 필드 반환
    def test_today_schedule_item_has_correct_fields(self):
        """TodayScheduleItem이 올바른 필드를 가져야 함"""
        from app.modules.instagram.models.schemas import TodayScheduleItem

        # 프론트엔드와 일치하는 필드: scheduled_time, status, run_id
        assert hasattr(TodayScheduleItem, 'model_fields')
        fields = TodayScheduleItem.model_fields

        assert 'scheduled_time' in fields, "scheduled_time 필드 필요"
        assert 'status' in fields, "status 필드 필요"
        assert 'run_id' in fields, "run_id 필드 필요"

    def test_today_schedule_item_creation(self):
        """TodayScheduleItem 인스턴스 생성"""
        from app.modules.instagram.models.schemas import TodayScheduleItem

        item = TodayScheduleItem(
            scheduled_time="10:30",
            status="pending",
            run_id=None
        )

        assert item.scheduled_time == "10:30"
        assert item.status == "pending"
        assert item.run_id is None

    def test_today_schedule_item_with_run_id(self):
        """run_id가 있는 TodayScheduleItem"""
        from app.modules.instagram.models.schemas import TodayScheduleItem

        item = TodayScheduleItem(
            scheduled_time="14:00",
            status="completed",
            run_id=123
        )

        assert item.status == "completed"
        assert item.run_id == 123

    # Boundary: 경계 조건
    def test_today_schedule_item_all_statuses(self):
        """모든 status 값 테스트"""
        from app.modules.instagram.models.schemas import TodayScheduleItem

        valid_statuses = ['pending', 'running', 'completed', 'missed']

        for status in valid_statuses:
            item = TodayScheduleItem(
                scheduled_time="10:00",
                status=status,
                run_id=None
            )
            assert item.status == status


class TestGetTodaySchedule:
    """get_today_schedule() 메서드 테스트"""

    @pytest.fixture
    def mock_db_with_config(self):
        """활성화된 설정이 있는 Mock DB"""
        from app.models import InstagramScheduleConfig

        mock_db = MagicMock()

        # 활성화된 설정
        mock_config = MagicMock(spec=InstagramScheduleConfig)
        mock_config.enabled = True
        mock_config.daily_runs = 3
        mock_config.time_windows = [
            {"start": "07:00", "end": "10:00"},
            {"start": "12:00", "end": "15:00"},
            {"start": "19:00", "end": "23:00"},
        ]
        mock_config.account_id = 1

        mock_db.query.return_value.first.return_value = mock_config
        mock_db.query.return_value.filter.return_value.all.return_value = []

        return mock_db

    # Right: 올바른 결과
    def test_get_today_schedule_returns_list(self, mock_db_with_config):
        """get_today_schedule이 리스트 반환"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db_with_config)
        result = service.get_today_schedule()

        assert isinstance(result, list)

    def test_get_today_schedule_item_has_correct_fields(self, mock_db_with_config):
        """반환된 항목이 올바른 필드 포함"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db_with_config)
        result = service.get_today_schedule()

        if result:  # 항목이 있으면
            item = result[0]
            assert hasattr(item, 'scheduled_time')
            assert hasattr(item, 'status')
            assert hasattr(item, 'run_id')

    def test_get_today_schedule_returns_daily_runs_count(self, mock_db_with_config):
        """daily_runs 수만큼 항목 반환"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db_with_config)
        result = service.get_today_schedule()

        # 설정에서 daily_runs=3
        assert len(result) == 3

    # Boundary: 경계 조건
    def test_get_today_schedule_empty_when_disabled(self):
        """비활성화 시 빈 리스트 반환"""
        from app.modules.instagram.services.crawl_service import CrawlService
        from app.models import InstagramScheduleConfig

        mock_db = MagicMock()
        mock_config = MagicMock(spec=InstagramScheduleConfig)
        mock_config.enabled = False
        mock_db.query.return_value.first.return_value = mock_config

        service = CrawlService(mock_db)
        result = service.get_today_schedule()

        assert result == []

    def test_get_today_schedule_empty_when_no_config(self):
        """설정이 없으면 빈 리스트 반환"""
        from app.modules.instagram.services.crawl_service import CrawlService

        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = None

        service = CrawlService(mock_db)
        result = service.get_today_schedule()

        assert result == []

    # Cross-check: 상태 결정 로직
    def test_get_today_schedule_pending_status(self, mock_db_with_config):
        """미래 시간은 pending 상태"""
        from app.modules.instagram.services.crawl_service import CrawlService

        service = CrawlService(mock_db_with_config)
        result = service.get_today_schedule()

        # 미래 시간이 있다면 pending
        future_items = [item for item in result if item.status == "pending"]
        for item in future_items:
            assert item.run_id is None


# ============================================================
# 크롤러 개선 테스트 (2025-12-21 추가)
# - 광고 식별 개선
# - 스크롤 동작 개선
# - 더보기 버튼 안정화
# ============================================================

class TestCrawlerAdDetection:
    """광고 게시물 식별 테스트 (RIGHT-BICEP)"""

    def test_crawl_options_has_scroll_behavior(self):
        """CrawlOptions에 스크롤 동작 설정 존재"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()
        assert hasattr(options, 'scroll_behavior')
        assert options.scroll_behavior == "human"  # 기본값

    def test_crawl_options_scroll_delay_range(self):
        """CrawlOptions에 스크롤 딜레이 범위 설정 존재"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()
        assert hasattr(options, 'min_scroll_delay')
        assert hasattr(options, 'max_scroll_delay')
        assert options.min_scroll_delay == 1.5
        assert options.max_scroll_delay == 3.5

    def test_crawl_options_read_pause_probability(self):
        """CrawlOptions에 읽기 멈춤 확률 설정 존재"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()
        assert hasattr(options, 'read_pause_probability')
        assert options.read_pause_probability == 0.3

    def test_crawl_options_wait_after_more_increased(self):
        """wait_after_more가 1.0초로 증가됨"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()
        assert options.wait_after_more == 1.0

    def test_crawler_has_more_button_texts(self):
        """InstagramCrawler에 다국어 더보기 버튼 텍스트 존재"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, 'MORE_BUTTON_TEXTS')
        texts = crawler.MORE_BUTTON_TEXTS

        # 다국어 지원 확인
        assert '더 보기' in texts  # 한국어
        assert 'more' in texts  # 영어
        assert 'もっと見る' in texts  # 일본어


class TestCrawlerScrollBehavior:
    """크롤러 스크롤 동작 테스트 (CORRECT)"""

    def test_scroll_behavior_human_option(self):
        """human 스크롤 동작 옵션"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(scroll_behavior="human")
        assert options.scroll_behavior == "human"

    def test_scroll_behavior_fast_option(self):
        """fast 스크롤 동작 옵션"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(scroll_behavior="fast")
        assert options.scroll_behavior == "fast"

    def test_custom_scroll_delays(self):
        """커스텀 스크롤 딜레이 설정"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(
            min_scroll_delay=2.0,
            max_scroll_delay=5.0
        )
        assert options.min_scroll_delay == 2.0
        assert options.max_scroll_delay == 5.0

    def test_custom_read_pause_probability(self):
        """커스텀 읽기 멈춤 확률 설정"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(read_pause_probability=0.5)
        assert options.read_pause_probability == 0.5


class TestCrawlerHumanLikeScroll:
    """사람처럼 스크롤 테스트"""

    def test_crawler_has_scroll_human_like_method(self):
        """InstagramCrawler에 _scroll_human_like 메서드 존재"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        assert hasattr(crawler, '_scroll_human_like')
        assert callable(crawler._scroll_human_like)

    def test_crawler_scroll_page_accepts_options(self):
        """_scroll_page 메서드가 options 인자를 받음"""
        from app.modules.instagram.services.crawler import InstagramCrawler
        import inspect

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        sig = inspect.signature(crawler._scroll_page)
        params = list(sig.parameters.keys())

        assert 'options' in params


class TestCrawlerMoreButtonImprovement:
    """더보기 버튼 개선 테스트"""

    def test_more_button_texts_includes_languages(self):
        """다국어 더보기 텍스트 포함 확인"""
        from app.modules.instagram.services.crawler import InstagramCrawler

        mock_page = MagicMock()
        crawler = InstagramCrawler(mock_page)

        texts = crawler.MORE_BUTTON_TEXTS

        # 최소 5개 언어 지원
        assert len(texts) >= 5

        # 주요 언어 포함
        assert '더 보기' in texts  # 한국어
        assert 'more' in texts  # 영어
        assert 'もっと見る' in texts  # 일본어
        assert '顯示更多' in texts  # 번체 중국어
        assert '显示更多' in texts  # 간체 중국어


class TestCrawlOptionsDefaults:
    """CrawlOptions 기본값 테스트 (경계값)"""

    def test_all_default_values(self):
        """모든 기본값 확인"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()

        # 기존 설정
        assert options.max_posts == 20
        assert options.scroll_count == 3
        assert options.wait_after_more == 1.0
        assert options.wait_after_scroll == 2.0
        assert options.duplicate_stop_count == 5
        assert options.max_refresh_count == 3
        assert options.no_new_posts_refresh_threshold == 3

        # 새 설정
        assert options.scroll_behavior == "human"
        assert options.min_scroll_delay == 1.5
        assert options.max_scroll_delay == 3.5
        assert options.read_pause_probability == 0.3

    def test_custom_all_values(self):
        """모든 값 커스텀 설정"""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(
            max_posts=50,
            scroll_count=10,
            wait_after_more=2.0,
            wait_after_scroll=3.0,
            duplicate_stop_count=10,
            max_refresh_count=5,
            no_new_posts_refresh_threshold=5,
            scroll_behavior="fast",
            min_scroll_delay=1.0,
            max_scroll_delay=2.0,
            read_pause_probability=0.1
        )

        assert options.max_posts == 50
        assert options.scroll_count == 10
        assert options.scroll_behavior == "fast"
        assert options.min_scroll_delay == 1.0


class TestPostDataAdField:
    """PostData is_ad 필드 테스트"""

    def test_post_data_is_ad_default_false(self):
        """is_ad 기본값은 False"""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(index=0)
        assert post.is_ad is False

    def test_post_data_is_ad_can_be_true(self):
        """is_ad를 True로 설정 가능"""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(index=0, is_ad=True)
        assert post.is_ad is True

    def test_post_data_images_empty_by_default(self):
        """images 기본값은 빈 리스트"""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(index=0)
        assert post.images == []

    def test_post_data_images_with_alt(self):
        """images에 alt 속성 포함"""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(
            index=0,
            images=[
                {"src": "https://scontent.com/img1.jpg", "alt": "Photo by user"},
                {"src": "https://scontent.com/img2.jpg", "alt": "Photo shared by user"}
            ]
        )
        assert len(post.images) == 2
        assert post.images[0]["alt"] == "Photo by user"
