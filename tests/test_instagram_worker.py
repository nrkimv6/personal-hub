"""Instagram Worker 테스트 - RIGHT-BICEP 원칙 적용.

테스트 대상: InstagramScheduler 및 관련 서비스

RIGHT-BICEP:
- Right: 정상 동작 테스트
- Boundary: 경계 조건 테스트
- Inverse: 역 관계 테스트
- Cross-check: 교차 검증
- Error: 에러 처리 테스트
- Performance: 성능 테스트

Note:
- CrawlRequest, CrawlSchedule, CrawlScheduleRun 모델 테스트는 test_crawl_models.py에서 수행
- 이 파일은 스케줄러 로직과 서비스 레이어 테스트에 집중
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

from app.modules.instagram.services.scheduler import InstagramScheduler
from app.modules.instagram.models.schemas import TimeWindow


# ============================================================
# InstagramScheduler 테스트 - RIGHT
# ============================================================

class TestInstagramSchedulerRight:
    """InstagramScheduler 정상 동작 테스트."""

    def test_generate_daily_schedule_returns_correct_count(self):
        """일일 스케줄이 지정된 횟수만큼 생성되어야 함."""
        scheduler = InstagramScheduler(
            daily_runs=3,
            time_windows=[
                TimeWindow(start="09:00", end="12:00"),
                TimeWindow(start="14:00", end="17:00"),
                TimeWindow(start="19:00", end="22:00"),
            ]
        )
        schedule = scheduler.generate_daily_schedule()

        assert len(schedule) == 3

    def test_schedule_times_within_windows(self):
        """생성된 시간이 시간 윈도우 내에 있어야 함."""
        time_windows = [
            TimeWindow(start="09:00", end="12:00"),
            TimeWindow(start="14:00", end="17:00"),
            TimeWindow(start="19:00", end="22:00"),
        ]
        scheduler = InstagramScheduler(daily_runs=3, time_windows=time_windows)
        schedule = scheduler.generate_daily_schedule()

        for scheduled_time in schedule:
            time_str = scheduled_time.strftime("%H:%M")
            is_in_window = any(
                window.start <= time_str <= window.end
                for window in time_windows
            )
            assert is_in_window, f"Time {time_str} is not in any window"

    def test_deterministic_schedule_same_day(self):
        """같은 날짜에 대해 동일한 스케줄이 생성되어야 함."""
        scheduler = InstagramScheduler(
            daily_runs=3,
            time_windows=[TimeWindow(start="09:00", end="22:00")]
        )
        test_date = datetime.now().date()

        schedule1 = scheduler.generate_daily_schedule(test_date)
        schedule2 = scheduler.generate_daily_schedule(test_date)

        assert schedule1 == schedule2

    def test_schedule_is_sorted(self):
        """스케줄이 시간순으로 정렬되어야 함."""
        scheduler = InstagramScheduler(
            daily_runs=5,
            time_windows=[TimeWindow(start="08:00", end="23:00")]
        )
        schedule = scheduler.generate_daily_schedule()

        for i in range(len(schedule) - 1):
            assert schedule[i] <= schedule[i + 1]


# ============================================================
# InstagramScheduler 테스트 - BOUNDARY
# ============================================================

class TestInstagramSchedulerBoundary:
    """InstagramScheduler 경계값 테스트."""

    def test_single_run_schedule(self):
        """일일 1회 스케줄 생성."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="11:00")]
        )
        schedule = scheduler.generate_daily_schedule()

        assert len(schedule) == 1

    def test_more_runs_than_windows(self):
        """실행 횟수가 범위 윈도우 수보다 많아도 요청 횟수만큼 생성."""
        scheduler = InstagramScheduler(
            daily_runs=10,
            time_windows=[
                TimeWindow(start="09:00", end="12:00"),
                TimeWindow(start="14:00", end="17:00"),
            ]
        )
        schedule = scheduler.generate_daily_schedule()

        assert len(schedule) == 10

    def test_exact_time_windows_are_ignored_for_repair(self):
        """start == end legacy 윈도우는 실행 슬롯으로 해석하지 않음."""
        run_date = datetime(2026, 5, 3).date()
        scheduler = InstagramScheduler(
            daily_runs=3,
            time_windows=[
                TimeWindow(start="07:00", end="07:00"),
                TimeWindow(start="12:00", end="12:00"),
                TimeWindow(start="18:30", end="18:30"),
            ],
        )

        schedule = scheduler.generate_daily_schedule(run_date)

        assert schedule == []

    def test_default_time_windows(self):
        """기본 시간 윈도우 사용."""
        scheduler = InstagramScheduler()
        schedule = scheduler.generate_daily_schedule()

        assert len(schedule) == 3  # 기본 daily_runs


# ============================================================
# InstagramScheduler 테스트 - TIME
# ============================================================

class TestInstagramSchedulerTime:
    """InstagramScheduler 시간 관련 테스트."""

    def test_should_run_now_within_tolerance(self):
        """허용 오차 내에서 실행 여부 확인."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)

            should_run = scheduler.should_run_now(
                last_run=None,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is True

    def test_should_not_run_outside_tolerance(self):
        """허용 오차 외에서는 실행하지 않아야 함."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=10)

            should_run = scheduler.should_run_now(
                last_run=None,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is False

    def test_should_not_run_if_already_ran(self):
        """이미 실행된 경우 재실행 안함."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = run_time + timedelta(minutes=1)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5
            )

            assert should_run is False

    def test_should_run_for_previous_day_overnight_slot(self):
        """자정 이후에 걸친 전날 윈도우 후보도 실행 판정에 포함."""
        today = datetime.now().date()
        scheduler = None
        run_time = None
        for index in range(20):
            candidate_scheduler = InstagramScheduler(
                daily_runs=1,
                time_windows=[TimeWindow(start="23:59", end="00:01")],
                seed_prefix=f"overnight_due_test_{index}",
            )
            candidates = candidate_scheduler.generate_daily_schedule(today - timedelta(days=1))
            run_time = next((candidate for candidate in candidates if candidate.date() == today), None)
            if run_time is not None:
                scheduler = candidate_scheduler
                break

        assert scheduler is not None
        assert run_time is not None

        assert scheduler.should_run_now(
            last_run=None,
            now=run_time + timedelta(minutes=1),
            tolerance_minutes=5,
        ) is True

    def test_get_next_run_time(self):
        """다음 실행 시간 가져오기."""
        scheduler = InstagramScheduler(
            daily_runs=3,
            time_windows=[
                TimeWindow(start="09:00", end="12:00"),
                TimeWindow(start="14:00", end="17:00"),
                TimeWindow(start="19:00", end="22:00"),
            ]
        )

        today = datetime.now().date()
        midnight = datetime.combine(today, datetime.min.time())

        next_run = scheduler.get_next_run_time(midnight)

        assert next_run is not None
        assert next_run > midnight


# ============================================================
# InstagramScheduler 테스트 - MIN INTERVAL
# ============================================================

class TestInstagramSchedulerMinInterval:
    """InstagramScheduler 최소 실행 간격 테스트."""

    def test_should_run_when_no_min_interval(self):
        """min_interval이 0이면 제한 없음."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = run_time - timedelta(minutes=30)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=0
            )

            assert should_run is True

    def test_should_not_run_within_min_interval(self):
        """min_interval 이내에는 실행하지 않음."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = now - timedelta(minutes=30)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2
            )

            assert should_run is False

    def test_should_run_after_min_interval(self):
        """min_interval 경과 후에는 실행."""
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")]
        )

        today = datetime.now().date()
        schedule = scheduler.generate_daily_schedule(today)

        if schedule:
            run_time = schedule[0]
            now = run_time + timedelta(minutes=2)
            last_run = now - timedelta(hours=3)

            should_run = scheduler.should_run_now(
                last_run=last_run,
                now=now,
                tolerance_minutes=5,
                min_interval_hours=2
            )

            assert should_run is True


# ============================================================
# Crawler 옵션 테스트
# ============================================================

class TestCrawlOptions:
    """CrawlOptions 테스트."""

    def test_default_values(self):
        """기본값 확인."""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions()

        assert options.max_posts == 20
        assert options.scroll_count == 3
        assert options.wait_after_more == 1.0
        assert options.wait_after_scroll == 2.0
        assert options.duplicate_stop_count == 5
        assert options.max_refresh_count == 3
        assert options.scroll_behavior == "human"

    def test_custom_values(self):
        """커스텀 값 설정."""
        from app.modules.instagram.services.crawler import CrawlOptions

        options = CrawlOptions(
            max_posts=50,
            scroll_count=10,
            duplicate_stop_count=10
        )

        assert options.max_posts == 50
        assert options.scroll_count == 10
        assert options.duplicate_stop_count == 10


# ============================================================
# CrawlResult 테스트
# ============================================================

class TestCrawlResult:
    """CrawlResult 테스트."""

    def test_creation(self):
        """CrawlResult 생성 테스트."""
        from app.modules.instagram.services.crawler import CrawlResult, PostData

        result = CrawlResult(
            posts=[PostData(index=0, account="test")],
            stop_reason="max_posts_reached",
            duplicate_count=3,
            scroll_performed=5,
            refresh_count=1,
            config_snapshot={"max_posts": 20}
        )

        assert result.stop_reason == "max_posts_reached"
        assert result.duplicate_count == 3
        assert result.scroll_performed == 5
        assert result.refresh_count == 1
        assert len(result.posts) == 1


# ============================================================
# PostData 테스트
# ============================================================

class TestPostData:
    """PostData 테스트."""

    def test_default_values(self):
        """PostData 기본값."""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(index=0)

        assert post.is_ad is False
        assert post.images == []
        assert post.account is None
        assert post.url is None

    def test_full_post_data(self):
        """전체 필드가 있는 PostData."""
        from app.modules.instagram.services.crawler import PostData

        post = PostData(
            index=0,
            account="testuser",
            url="https://www.instagram.com/p/ABC123/",
            caption="Test caption",
            images=[{"src": "https://example.com/img.jpg", "alt": "test"}],
            is_ad=True
        )

        assert post.account == "testuser"
        assert post.is_ad is True
        assert len(post.images) == 1


# ============================================================
# ScheduledCrawlWorker 테스트
# ============================================================

class TestScheduledCrawlWorkerRight:
    """ScheduledCrawlWorker 정상 동작 테스트."""

    def test_init_with_default_interval(self):
        """기본 check_interval로 초기화."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker()
        assert worker.check_interval == 30
        assert worker.name == "scheduled_worker"
        assert worker.worker_type == "scheduled"

    def test_init_with_custom_interval(self):
        """커스텀 check_interval로 초기화."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(check_interval=60)
        assert worker.check_interval == 60

    def test_get_loop_interval(self):
        """루프 간격이 1초로 설정됨."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker()
        assert worker._get_loop_interval() == 1.0


class TestScheduledCrawlWorkerBoundary:
    """ScheduledCrawlWorker 경계값 테스트."""

    def test_zero_check_interval(self):
        """check_interval이 0인 경우."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker(check_interval=0)
        assert worker.check_interval == 0


# ============================================================
# OnDemandCrawlWorker 테스트
# ============================================================

class TestOnDemandCrawlWorkerRight:
    """OnDemandCrawlWorker 정상 동작 테스트."""

    def test_init_with_default_max_requests(self):
        """기본 max_concurrent_requests로 초기화."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker()
        assert worker.max_concurrent_requests == 5
        assert worker.name == "ondemand_worker"
        assert worker.worker_type == "ondemand"

    def test_init_with_custom_max_requests(self):
        """커스텀 max_concurrent_requests로 초기화."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker(max_concurrent_requests=10)
        assert worker.max_concurrent_requests == 10

    def test_get_loop_interval(self):
        """루프 간격이 1초로 설정됨."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker()
        assert worker._get_loop_interval() == 1.0


class TestOnDemandCrawlWorkerBoundary:
    """OnDemandCrawlWorker 경계값 테스트."""

    def test_single_max_requests(self):
        """max_concurrent_requests가 1인 경우."""
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        worker = OnDemandCrawlWorker(max_concurrent_requests=1)
        assert worker.max_concurrent_requests == 1


# ============================================================
# CrawlWorkerBase 테스트
# ============================================================

class TestCrawlWorkerBaseRight:
    """CrawlWorkerBase 공통 기능 테스트."""

    def test_worker_base_initialization(self):
        """워커 기본 상태 초기화."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker()
        assert worker.shutdown_event is not None
        assert worker._running_tasks == set()

    def test_worker_type_attribute(self):
        """워커 타입 구분."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker
        from app.worker.ondemand_worker import OnDemandCrawlWorker

        scheduled = ScheduledCrawlWorker()
        ondemand = OnDemandCrawlWorker()

        assert scheduled.worker_type == "scheduled"
        assert ondemand.worker_type == "ondemand"

    def test_request_shutdown_sets_event(self):
        """request_shutdown 호출 시 이벤트 설정."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker()
        assert not worker.shutdown_event.is_set()

        worker.request_shutdown()
        assert worker.shutdown_event.is_set()
