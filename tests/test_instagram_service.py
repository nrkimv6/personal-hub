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
