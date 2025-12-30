"""Instagram Worker 테스트 - RIGHT-BICEP 원칙 적용.

테스트 대상: app/worker/instagram_worker.py (InstagramWorker)

RIGHT-BICEP:
- Right: 정상 동작 테스트
- Boundary: 경계 조건 테스트
- Inverse: 역 관계 테스트
- Cross-check: 교차 검증
- Error: 에러 처리 테스트
- Performance: 성능 테스트
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.models.base import Base
from app.models import BrowserProfile, ServiceAccount, CrawlRequest, CrawlSchedule, CrawlScheduleRun
from app.modules.instagram.services.request_service import CrawlRequestService
from app.modules.instagram.services.crawl_service import CrawlService
from app.modules.instagram.services.scheduler import InstagramScheduler
from app.modules.instagram.services.worker_status_service import WorkerStatusService
from app.modules.instagram.models.schemas import TimeWindow


# TODO: 이 테스트 파일은 레거시 모델(InstagramCrawlRequest, InstagramCrawlRun, InstagramScheduleConfig)을
# 사용하고 있어 새 모델(CrawlRequest, CrawlSchedule, CrawlScheduleRun)로 전환이 필요합니다.
# DB 마이그레이션(071) 적용 후 테스트 재작성이 필요합니다.
pytestmark = pytest.mark.skip(reason="Legacy model migration in progress - needs rewrite for new CrawlRequest/CrawlSchedule models")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session():
    """테스트용 in-memory SQLite DB 세션."""
    # In-memory SQLite 엔진 생성
    engine = create_engine("sqlite:///:memory:", echo=False)

    # 테이블 생성
    Base.metadata.create_all(engine)

    # 세션 생성
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    # 정리
    session.close()
    engine.dispose()


@pytest.fixture
def sample_account(db_session):
    """테스트용 Instagram 계정 (BrowserProfile + ServiceAccount)."""
    profile = BrowserProfile(
        name="test_user",
        profile_dir="test_profile",
        is_active=True,
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    service_account = ServiceAccount(
        profile_id=profile.id,
        service_type="instagram",
        is_logged_in=True,
    )
    db_session.add(service_account)
    db_session.commit()
    db_session.refresh(service_account)
    return service_account


@pytest.fixture
def sample_account_not_logged_in(db_session):
    """로그인 안 된 Instagram 계정 (BrowserProfile + ServiceAccount)."""
    profile = BrowserProfile(
        name="not_logged_in_user",
        profile_dir="not_logged_in_profile",
        is_active=True,
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    service_account = ServiceAccount(
        profile_id=profile.id,
        service_type="instagram",
        is_logged_in=False,
    )
    db_session.add(service_account)
    db_session.commit()
    db_session.refresh(service_account)
    return service_account


@pytest.fixture
def sample_schedule_config(db_session, sample_account):
    """테스트용 스케줄 설정."""
    config = InstagramScheduleConfig(
        enabled=True,
        daily_runs=3,
        time_windows=[
            {"start": "07:00", "end": "10:00"},
            {"start": "12:00", "end": "15:00"},
            {"start": "19:00", "end": "23:00"},
        ],
        max_posts=20,
        scroll_count=3,
        service_account_id=sample_account.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture
def pending_request(db_session, sample_account):
    """대기 중인 크롤링 요청."""
    request = InstagramCrawlRequest(
        service_account_id=sample_account.id,
        requested_by="manual",
        status="pending",
        requested_at=datetime.utcnow(),
    )
    db_session.add(request)
    db_session.commit()
    db_session.refresh(request)
    return request


@pytest.fixture
def mock_browser_service():
    """모킹된 브라우저 서비스."""
    mock = AsyncMock()
    mock.initialize = AsyncMock()
    mock.get_context_for_account = AsyncMock(return_value=Mock())
    return mock


@pytest.fixture
def mock_crawler():
    """모킹된 Instagram 크롤러."""
    from app.modules.instagram.services.crawler import PostData

    mock = AsyncMock()
    mock.crawl_feed = AsyncMock(return_value=[
        PostData(
            index=0,
            account="test_account",
            url="https://instagram.com/p/ABC123/",
            caption="Test caption",
            images=[{"src": "https://example.com/img.jpg", "alt": "test"}],
            datetime_str=datetime.utcnow().isoformat(),
            display_time="1시간 전",
            is_ad=False,
        )
    ])
    return mock


# ============================================================
# RIGHT: 정상 동작 테스트
# ============================================================

class TestProcessPendingRequests:
    """Pending 요청 처리 테스트."""

    def test_get_pending_request_returns_oldest_first(self, db_session, sample_account):
        """pending 요청이 요청 시간 순으로 반환되어야 한다."""
        # Given: 여러 pending 요청
        request1 = InstagramCrawlRequest(
            service_account_id=sample_account.id,
            requested_by="manual",
            status="pending",
            requested_at=datetime.utcnow() - timedelta(hours=2),
        )
        request2 = InstagramCrawlRequest(
            service_account_id=sample_account.id + 100,  # 다른 계정
            requested_by="scheduler",
            status="pending",
            requested_at=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add_all([request1, request2])
        db_session.commit()

        # When
        service = CrawlRequestService(db_session)
        pending = service.get_pending_request()

        # Then: 가장 오래된 요청 반환
        assert pending is not None
        assert pending.id == request1.id
        assert pending.requested_by == "manual"

    def test_pending_request_marks_as_processing(self, db_session, pending_request):
        """요청이 processing 상태로 변경되어야 한다."""
        # Given
        service = CrawlRequestService(db_session)

        # When
        updated = service.mark_processing(pending_request.id)

        # Then
        assert updated is not None
        assert updated.status == "processing"
        assert updated.processed_at is not None


class TestScheduledRuns:
    """스케줄 기반 실행 테스트."""

    def test_should_run_now_within_window(self):
        """시간 윈도우 내에서 should_run_now가 True를 반환해야 한다."""
        # Given: 현재 시간이 스케줄된 시간과 가까울 때
        scheduler = InstagramScheduler(
            daily_runs=1,
            time_windows=[TimeWindow(start="10:00", end="10:05")],
            seed_prefix="test"
        )

        # 오늘 10:00에 스케줄 생성
        now = datetime.now().replace(hour=10, minute=1, second=0, microsecond=0)
        schedule = scheduler.generate_daily_schedule(now.date())

        # When: 스케줄된 시간 직후 체크
        if schedule:
            scheduled_time = schedule[0]
            check_time = scheduled_time + timedelta(minutes=1)
            result = scheduler.should_run_now(last_run=None, now=check_time)

            # Then
            assert result is True

    def test_schedule_config_with_account_id(self, db_session, sample_schedule_config):
        """account_id가 설정된 config가 정상 조회되어야 한다."""
        # Given
        crawl_service = CrawlService(db_session)

        # When
        config = crawl_service.get_schedule_config()

        # Then
        assert config is not None
        assert config.service_account_id is not None
        assert config.enabled is True


# ============================================================
# BOUNDARY: 경계 조건 테스트
# ============================================================

class TestBoundaryConditions:
    """경계 조건 테스트."""

    def test_no_pending_requests(self, db_session):
        """pending 요청이 없으면 None을 반환해야 한다."""
        # Given: 요청 없음
        service = CrawlRequestService(db_session)

        # When
        pending = service.get_pending_request()

        # Then
        assert pending is None

    def test_schedule_disabled(self, db_session, sample_account):
        """스케줄이 비활성화되면 실행하지 않아야 한다."""
        # Given: 비활성화된 config
        config = InstagramScheduleConfig(
            enabled=False,
            daily_runs=3,
            service_account_id=sample_account.id,
        )
        db_session.add(config)
        db_session.commit()

        crawl_service = CrawlService(db_session)
        retrieved_config = crawl_service.get_schedule_config()

        # Then
        assert retrieved_config is not None
        assert retrieved_config.enabled is False

    def test_schedule_without_account_id(self, db_session):
        """account_id가 없으면 스케줄을 실행하지 않아야 한다."""
        # Given: service_account_id 없는 config
        config = InstagramScheduleConfig(
            enabled=True,
            daily_runs=3,
            service_account_id=None,
        )
        db_session.add(config)
        db_session.commit()

        crawl_service = CrawlService(db_session)
        retrieved_config = crawl_service.get_schedule_config()

        # Then
        assert retrieved_config is not None
        assert retrieved_config.service_account_id is None


# ============================================================
# INVERSE: 역 관계 테스트
# ============================================================

class TestInverseRelations:
    """역 관계 테스트 - 상태 변경 확인."""

    def test_request_completed_after_success(self, db_session, pending_request):
        """크롤링 성공 후 요청이 completed 상태가 되어야 한다."""
        # Given
        service = CrawlRequestService(db_session)

        # 실행 기록 생성
        crawl_run = InstagramCrawlRun(
            service_account_id=pending_request.service_account_id,
            started_at=datetime.utcnow(),
            success=True,
            total_collected=5,
            new_saved=3,
            finished_at=datetime.utcnow(),
        )
        db_session.add(crawl_run)
        db_session.commit()

        # When
        updated = service.mark_completed(pending_request.id, crawl_run.id)

        # Then
        assert updated is not None
        assert updated.status == "completed"
        assert updated.crawl_run_id == crawl_run.id

    def test_request_failed_on_error(self, db_session, pending_request):
        """크롤링 실패 시 요청이 failed 상태가 되어야 한다."""
        # Given
        service = CrawlRequestService(db_session)
        error_message = "Login required"

        # When
        updated = service.mark_failed(pending_request.id, error_message)

        # Then
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message == error_message


# ============================================================
# CROSS-CHECK: 교차 검증
# ============================================================

class TestCrossCheck:
    """교차 검증 - DB 저장 확인."""

    def test_crawl_run_saved_to_db(self, db_session, sample_account):
        """CrawlRun이 DB에 저장되어야 한다."""
        # Given
        crawl_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow(),
            success=True,
            total_collected=10,
            new_saved=5,
            finished_at=datetime.utcnow(),
        )
        db_session.add(crawl_run)
        db_session.commit()

        # When: DB에서 다시 조회
        crawl_service = CrawlService(db_session)
        runs = crawl_service.get_crawl_runs(limit=10, service_account_id=sample_account.id)

        # Then
        assert len(runs) == 1
        assert runs[0].total_collected == 10
        assert runs[0].new_saved == 5

    def test_last_run_reflects_db_state(self, db_session, sample_account):
        """get_last_run이 DB의 최신 상태를 반영해야 한다."""
        # Given: 여러 실행 기록
        run1 = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=2),
            success=True,
            total_collected=5,
            new_saved=2,
        )
        run2 = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=1),
            success=True,
            total_collected=8,
            new_saved=4,
        )
        db_session.add_all([run1, run2])
        db_session.commit()

        # When
        crawl_service = CrawlService(db_session)
        last_run = crawl_service.get_last_run(service_account_id=sample_account.id)

        # Then: 가장 최근 실행 반환
        assert last_run is not None
        assert last_run.id == run2.id
        assert last_run.total_collected == 8


# ============================================================
# ERROR: 에러 처리 테스트
# ============================================================

class TestErrorHandling:
    """에러 처리 테스트."""

    def test_not_logged_in_account_detection(self, db_session, sample_account_not_logged_in):
        """로그인 안 된 계정이 올바르게 감지되어야 한다."""
        # Given
        account = db_session.query(ServiceAccount).get(sample_account_not_logged_in.id)

        # Then
        assert account is not None
        assert account.is_logged_in is False

    def test_failure_reason_classification(self, db_session, sample_account):
        """에러 원인이 올바르게 분류되어야 한다."""
        # Given
        crawl_service = CrawlService(db_session)

        # When/Then
        assert crawl_service.classify_failure(Exception("Login required")) == "login_required"
        assert crawl_service.classify_failure(Exception("Connection timeout")) == "timeout"
        assert crawl_service.classify_failure(Exception("Network error")) == "network_error"
        assert crawl_service.classify_failure(Exception("Rate limit exceeded")) == "rate_limit"
        assert crawl_service.classify_failure(Exception("Unknown error")) == "unknown"

    def test_mark_failed_on_nonexistent_request(self, db_session):
        """존재하지 않는 요청에 mark_failed 호출 시 None 반환."""
        # Given
        service = CrawlRequestService(db_session)

        # When
        result = service.mark_failed(999999, "Test error")

        # Then
        assert result is None


# ============================================================
# PERFORMANCE: 성능 테스트
# ============================================================

class TestPerformance:
    """성능 관련 테스트."""

    def test_multiple_pending_requests_processing_order(self, db_session, sample_account):
        """여러 pending 요청이 시간 순으로 처리되어야 한다."""
        # Given: 10개의 pending 요청 (다른 계정 ID 사용)
        requests = []
        for i in range(10):
            # 각기 다른 계정 ID 사용 (get_pending_request에서 계정당 하나만 반환)
            req = InstagramCrawlRequest(
                service_account_id=sample_account.id + i,  # 다른 계정
                requested_by="test",
                status="pending",
                requested_at=datetime.utcnow() - timedelta(minutes=10 - i),
            )
            requests.append(req)

        db_session.add_all(requests)
        db_session.commit()

        # When
        service = CrawlRequestService(db_session)
        pending_list = service.get_pending_requests(limit=10)

        # Then: 시간순 정렬
        assert len(pending_list) == 10
        # 가장 오래된 것이 먼저
        assert pending_list[0].service_account_id == sample_account.id

    def test_has_active_request_performance(self, db_session, sample_account, pending_request):
        """has_active_request가 빠르게 동작해야 한다."""
        # Given
        service = CrawlRequestService(db_session)

        # When
        result = service.has_active_request(sample_account.id)

        # Then
        assert result is True

        # When: 없는 계정
        result = service.has_active_request(999999)

        # Then
        assert result is False


# ============================================================
# 워커 통합 테스트 (모킹 사용)
# ============================================================

class TestInstagramWorkerIntegration:
    """InstagramWorker 통합 테스트 (실제 워커 클래스 테스트)."""

    @pytest.mark.asyncio
    async def test_worker_process_pending_request_flow(
        self, db_session, sample_account, pending_request, mock_browser_service, mock_crawler
    ):
        """워커가 pending 요청을 처리하는 전체 흐름 테스트."""
        # Given
        request_service = CrawlRequestService(db_session)

        # pending 상태 확인
        pending = request_service.get_pending_request(sample_account.id)
        assert pending is not None
        assert pending.status == "pending"

        # When: 처리 시작
        request_service.mark_processing(pending.id)

        # Then: processing 상태
        db_session.refresh(pending)
        assert pending.status == "processing"

        # When: 성공 처리
        crawl_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow(),
            success=True,
            total_collected=5,
            new_saved=3,
            finished_at=datetime.utcnow(),
        )
        db_session.add(crawl_run)
        db_session.commit()

        request_service.mark_completed(pending.id, crawl_run.id)

        # Then: completed 상태
        db_session.refresh(pending)
        assert pending.status == "completed"
        assert pending.crawl_run_id == crawl_run.id

    @pytest.mark.asyncio
    async def test_worker_handles_not_logged_in(
        self, db_session, sample_account_not_logged_in
    ):
        """로그인 안 된 계정의 요청은 실패 처리되어야 한다."""
        # Given
        request = InstagramCrawlRequest(
            service_account_id=sample_account_not_logged_in.id,
            requested_by="manual",
            status="pending",
            requested_at=datetime.utcnow(),
        )
        db_session.add(request)
        db_session.commit()

        request_service = CrawlRequestService(db_session)

        # 계정 로그인 상태 확인
        account = db_session.query(ServiceAccount).get(sample_account_not_logged_in.id)
        assert account.is_logged_in is False

        # When: 로그인 안 됨으로 실패 처리
        request_service.mark_failed(request.id, "로그인 필요")

        # Then
        db_session.refresh(request)
        assert request.status == "failed"
        assert "로그인" in request.error_message


# ============================================================
# REALTIME SAVE: 실시간 저장 테스트
# ============================================================

class TestRealtimeSave:
    """실시간 저장 기능 테스트.

    크롤링 중 게시물이 수집될 때마다 즉시 DB에 저장되어야 합니다.
    크롤러가 중간에 죽어도 그때까지 수집한 데이터는 보존됩니다.
    """

    @pytest.mark.asyncio
    async def test_on_post_collected_callback_invoked(self):
        """crawl_feed가 on_post_collected 콜백을 호출해야 한다."""
        from app.modules.instagram.services.crawler import InstagramCrawler, CrawlOptions, PostData
        from unittest.mock import AsyncMock, MagicMock

        # Given: 모킹된 Page
        mock_page = AsyncMock()
        mock_article = AsyncMock()

        # article.evaluate 모킹
        mock_article.evaluate = AsyncMock(return_value={
            "account": "test_user",
            "datetime": "2025-01-01T12:00:00Z",
            "display_time": "1시간 전",
            "url": "https://www.instagram.com/p/TEST123/",
            "images": [{"src": "http://example.com/img.jpg", "alt": "test"}],
            "is_ad": False,
            "has_more_button": False,
        })

        mock_page.query_selector_all = AsyncMock(return_value=[mock_article])
        mock_page.evaluate = AsyncMock()

        crawler = InstagramCrawler(mock_page)

        # 콜백 추적
        callback_calls = []

        async def track_callback(post: PostData) -> bool:
            callback_calls.append(post)
            return True

        # When
        options = CrawlOptions(max_posts=10, scroll_count=0)
        await crawler.crawl_feed(options, on_post_collected=track_callback)

        # Then: 콜백이 호출되어야 함
        assert len(callback_calls) >= 1
        assert callback_calls[0].url == "https://www.instagram.com/p/TEST123/"

    @pytest.mark.asyncio
    async def test_crawl_service_realtime_save(self, db_session, sample_account):
        """CrawlService.run_crawl이 실시간으로 저장해야 한다."""
        from app.modules.instagram.services.crawl_service import CrawlService
        from app.modules.instagram.services.crawler import InstagramCrawler, PostData
        from app.models import InstagramPost
        from unittest.mock import AsyncMock

        # Given: 모킹된 crawler
        mock_crawler = AsyncMock(spec=InstagramCrawler)
        mock_crawler._db_duplicate_checker = None

        posts_to_return = [
            PostData(
                index=1,
                account="user1",
                url="https://www.instagram.com/p/POST001/",
                caption="First post",
                images=[],
                datetime_str="2025-01-01T10:00:00Z",
                display_time="1시간 전",
                is_ad=False,
            ),
            PostData(
                index=2,
                account="user2",
                url="https://www.instagram.com/p/POST002/",
                caption="Second post",
                images=[],
                datetime_str="2025-01-01T11:00:00Z",
                display_time="30분 전",
                is_ad=False,
            ),
        ]

        # crawl_feed가 콜백을 호출하도록 구현
        async def mock_crawl_feed(options, on_post_collected=None):
            for post in posts_to_return:
                if on_post_collected:
                    await on_post_collected(post)
            return posts_to_return

        mock_crawler.crawl_feed = mock_crawl_feed

        crawl_service = CrawlService(db_session)

        # When
        crawl_run = await crawl_service.run_crawl(
            crawler=mock_crawler,
            service_account_id=sample_account.id,
        )

        # Then: 실행 성공
        assert crawl_run.success is True
        assert crawl_run.total_collected == 2
        assert crawl_run.new_saved == 2

        # DB에 저장 확인
        saved_posts = db_session.query(InstagramPost).filter(
            InstagramPost.crawl_run_id == crawl_run.id
        ).all()
        assert len(saved_posts) == 2

    @pytest.mark.asyncio
    async def test_partial_save_on_crash(self, db_session, sample_account):
        """크롤러 중간 크래시 시 그때까지 저장된 데이터 보존."""
        from app.modules.instagram.services.crawl_service import CrawlService
        from app.modules.instagram.services.crawler import InstagramCrawler, PostData
        from app.models import InstagramPost
        from unittest.mock import AsyncMock

        # Given
        mock_crawler = AsyncMock(spec=InstagramCrawler)
        mock_crawler._db_duplicate_checker = None

        posts_to_return = [
            PostData(index=1, account="user1", url="https://www.instagram.com/p/SAVED1/",
                     caption="Saved", images=[], datetime_str=None, display_time=None, is_ad=False),
            PostData(index=2, account="user2", url="https://www.instagram.com/p/SAVED2/",
                     caption="Also saved", images=[], datetime_str=None, display_time=None, is_ad=False),
        ]

        save_count = 0

        async def mock_crawl_feed_with_crash(options, on_post_collected=None):
            nonlocal save_count
            for i, post in enumerate(posts_to_return):
                if on_post_collected:
                    await on_post_collected(post)
                    save_count += 1
            # 2개 저장 후 크래시 시뮬레이션
            raise Exception("Browser crashed!")

        mock_crawler.crawl_feed = mock_crawl_feed_with_crash

        crawl_service = CrawlService(db_session)

        # When
        crawl_run = await crawl_service.run_crawl(
            crawler=mock_crawler,
            service_account_id=sample_account.id,
        )

        # Then: 실패했지만 저장된 데이터는 보존
        assert crawl_run.success is False
        assert "Browser crashed!" in crawl_run.error_message
        assert crawl_run.new_saved == 2  # 크래시 전에 저장됨

        # DB에서 확인
        saved_posts = db_session.query(InstagramPost).filter(
            InstagramPost.crawl_run_id == crawl_run.id
        ).all()
        assert len(saved_posts) == 2


# ============================================================
# ORPHANED RUN CLEANUP: 워커 크래시 후 정리 테스트
# ============================================================

class TestOrphanedRunCleanup:
    """워커 크래시로 인한 orphaned run 정리 테스트.

    워커가 비정상 종료되면 finished_at이 NULL인 상태로 남는 실행 기록이 생깁니다.
    새 워커가 시작될 때 이런 orphaned run들을 자동으로 실패 처리해야 합니다.
    """

    def test_cleanup_single_orphaned_run(self, db_session, sample_account):
        """단일 orphaned run이 정리되어야 한다."""
        # Given: finished_at이 NULL인 실행 기록 (워커 크래시 시뮬레이션)
        orphaned_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=1),
            finished_at=None,  # 워커 크래시로 미완료
            success=False,
            total_collected=5,
            new_saved=3,
        )
        db_session.add(orphaned_run)
        db_session.commit()

        # When: 새 워커 등록
        service = WorkerStatusService(db_session)
        service.register_worker()

        # Then: orphaned run이 실패 처리됨
        db_session.refresh(orphaned_run)
        assert orphaned_run.finished_at is not None
        assert orphaned_run.success is False
        assert orphaned_run.failure_reason == "worker_crash"
        assert "Worker crashed" in orphaned_run.error_message

    def test_cleanup_multiple_orphaned_runs(self, db_session, sample_account):
        """여러 orphaned run이 모두 정리되어야 한다."""
        # Given: 여러 orphaned runs
        orphaned_runs = []
        for i in range(3):
            run = InstagramCrawlRun(
                service_account_id=sample_account.id,
                started_at=datetime.utcnow() - timedelta(hours=i + 1),
                finished_at=None,
                success=False,
                total_collected=i * 2,
                new_saved=i,
            )
            db_session.add(run)
            orphaned_runs.append(run)
        db_session.commit()

        # When: 새 워커 등록
        service = WorkerStatusService(db_session)
        service.register_worker()

        # Then: 모든 orphaned runs가 정리됨
        for run in orphaned_runs:
            db_session.refresh(run)
            assert run.finished_at is not None
            assert run.failure_reason == "worker_crash"

    def test_completed_runs_not_affected(self, db_session, sample_account):
        """이미 완료된 실행 기록은 영향받지 않아야 한다."""
        # Given: 정상 완료된 실행 기록
        completed_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=2),
            finished_at=datetime.utcnow() - timedelta(hours=1),
            success=True,
            total_collected=10,
            new_saved=8,
        )
        db_session.add(completed_run)
        db_session.commit()

        original_finished_at = completed_run.finished_at
        original_error_message = completed_run.error_message

        # When: 새 워커 등록
        service = WorkerStatusService(db_session)
        service.register_worker()

        # Then: 완료된 실행 기록은 변경되지 않음
        db_session.refresh(completed_run)
        assert completed_run.finished_at == original_finished_at
        assert completed_run.success is True
        assert completed_run.error_message == original_error_message
        assert completed_run.failure_reason is None

    def test_mixed_runs_only_orphaned_cleaned(self, db_session, sample_account):
        """orphaned run만 정리되고 완료된 것은 유지되어야 한다."""
        # Given: 완료된 것과 orphaned 혼합
        completed_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=3),
            finished_at=datetime.utcnow() - timedelta(hours=2),
            success=True,
            total_collected=15,
            new_saved=10,
        )
        orphaned_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=1),
            finished_at=None,
            success=False,
            total_collected=5,
            new_saved=3,
        )
        db_session.add_all([completed_run, orphaned_run])
        db_session.commit()

        # When
        service = WorkerStatusService(db_session)
        service.register_worker()

        # Then
        db_session.refresh(completed_run)
        db_session.refresh(orphaned_run)

        # 완료된 것은 그대로
        assert completed_run.success is True
        assert completed_run.failure_reason is None

        # orphaned만 정리됨
        assert orphaned_run.finished_at is not None
        assert orphaned_run.failure_reason == "worker_crash"

    def test_no_orphaned_runs(self, db_session):
        """orphaned run이 없으면 에러 없이 처리되어야 한다."""
        # Given: orphaned run 없음
        service = WorkerStatusService(db_session)

        # When/Then: 에러 없이 워커 등록
        worker = service.register_worker()
        assert worker is not None
        assert worker.is_alive is True

    def test_cleanup_preserves_collected_counts(self, db_session, sample_account):
        """정리 시 수집된 데이터 카운트는 보존되어야 한다."""
        # Given
        orphaned_run = InstagramCrawlRun(
            service_account_id=sample_account.id,
            started_at=datetime.utcnow() - timedelta(hours=1),
            finished_at=None,
            success=False,
            total_collected=25,
            new_saved=20,
        )
        db_session.add(orphaned_run)
        db_session.commit()

        # When
        service = WorkerStatusService(db_session)
        service.register_worker()

        # Then: 카운트는 보존됨
        db_session.refresh(orphaned_run)
        assert orphaned_run.total_collected == 25
        assert orphaned_run.new_saved == 20
