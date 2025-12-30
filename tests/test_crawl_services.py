"""
크롤링 서비스 테스트 (CrawlRequestService, CrawlScheduleService)

RIGHT-BICEP, CORRECT 원칙 적용
"""

import pytest
from datetime import datetime, timedelta

from app.models import CrawlRequest, CrawlSchedule, CrawlScheduleRun
from app.services.crawl_request_service import CrawlRequestService
from app.services.crawl_schedule_service import CrawlScheduleService


class TestCrawlRequestService:
    """CrawlRequestService 테스트."""

    @pytest.fixture
    def service(self, test_db_session):
        return CrawlRequestService(test_db_session)

    def test_create_request_right(self, service):
        """[Right] 요청 생성이 올바르게 동작해야 함."""
        request = service.create_request(
            url="https://example.com",
            url_type=CrawlRequest.URL_TYPE_OTHER,
            requested_by="manual"
        )

        assert request.id is not None
        assert request.url == "https://example.com"
        assert request.url_type == CrawlRequest.URL_TYPE_OTHER
        assert request.status == CrawlRequest.STATUS_PENDING

    def test_get_pending_requests_right(self, service):
        """[Right] 대기 중인 요청 조회가 올바르게 동작해야 함."""
        # 여러 요청 생성
        service.create_request("https://1.com", CrawlRequest.URL_TYPE_INSTAGRAM)
        service.create_request("https://2.com", CrawlRequest.URL_TYPE_INSTAGRAM)
        service.create_request("https://3.com", CrawlRequest.URL_TYPE_OTHER)

        # Instagram 타입만 조회
        pending = service.get_pending_requests(url_type=CrawlRequest.URL_TYPE_INSTAGRAM)
        assert len(pending) >= 2
        for req in pending:
            assert req.url_type == CrawlRequest.URL_TYPE_INSTAGRAM

    def test_pick_request_right(self, service):
        """[Right] 요청 픽업이 올바르게 동작해야 함."""
        request = service.create_request("https://test.com", CrawlRequest.URL_TYPE_OTHER)

        picked = service.pick_request(request.id, "worker-001")

        assert picked is not None
        assert picked.status == CrawlRequest.STATUS_PICKED
        assert picked.worker_id == "worker-001"
        assert picked.picked_at is not None

    def test_pick_already_picked_request_error(self, service):
        """[Error] 이미 픽업된 요청은 픽업할 수 없어야 함."""
        request = service.create_request("https://test.com", CrawlRequest.URL_TYPE_OTHER)
        service.pick_request(request.id, "worker-001")

        # 다시 픽업 시도
        result = service.pick_request(request.id, "worker-002")
        assert result is None

    def test_complete_request_right(self, service):
        """[Right] 요청 완료 처리가 올바르게 동작해야 함."""
        request = service.create_request("https://test.com", CrawlRequest.URL_TYPE_OTHER)
        service.pick_request(request.id, "worker-001")
        service.start_processing(request.id)

        completed = service.complete_request(request.id, "crawled_page", 123)

        assert completed.status == CrawlRequest.STATUS_COMPLETED
        assert completed.result_type == "crawled_page"
        assert completed.result_id == 123
        assert completed.processed_at is not None

    def test_fail_request_right(self, service):
        """[Right] 요청 실패 처리가 올바르게 동작해야 함."""
        request = service.create_request("https://test.com", CrawlRequest.URL_TYPE_OTHER)
        service.pick_request(request.id, "worker-001")

        failed = service.fail_request(request.id, "Timeout error")

        assert failed.status == CrawlRequest.STATUS_FAILED
        assert failed.error_message == "Timeout error"

    def test_get_requests_paginated_right(self, service):
        """[Right] 페이징 조회가 올바르게 동작해야 함."""
        # 25개 요청 생성
        for i in range(25):
            service.create_request(f"https://test{i}.com", CrawlRequest.URL_TYPE_OTHER)

        result = service.get_requests_paginated(page=1, limit=10)

        assert result["total"] >= 25
        assert len(result["items"]) == 10
        assert result["page"] == 1
        assert result["pages"] >= 3

    def test_retry_failed_request_right(self, service):
        """[Right] 실패한 요청 재시도가 올바르게 동작해야 함."""
        request = service.create_request("https://test.com", CrawlRequest.URL_TYPE_OTHER)
        service.pick_request(request.id, "worker-001")
        service.fail_request(request.id, "First attempt failed")

        retry = service.retry_failed_request(request.id)

        assert retry is not None
        assert retry.id != request.id
        assert retry.url == request.url
        assert retry.requested_by == "retry"
        assert retry.retry_count == 1
        assert retry.status == CrawlRequest.STATUS_PENDING


class TestCrawlScheduleService:
    """CrawlScheduleService 테스트."""

    @pytest.fixture
    def service(self, test_db_session):
        return CrawlScheduleService(test_db_session)

    def test_create_schedule_right(self, service):
        """[Right] 스케줄 생성이 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"test_schedule_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            display_name="테스트 스케줄",
            target_config={"account_id": 1, "max_posts": 100},
            schedule_value='{"times": ["09:00", "14:00"]}',
            enabled=True
        )

        assert schedule.id is not None
        assert schedule.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED
        assert schedule.get_target_config()["account_id"] == 1

    def test_get_schedule_by_name_right(self, service):
        """[Right] 이름으로 스케줄 조회가 올바르게 동작해야 함."""
        name = f"unique_schedule_{datetime.now().timestamp()}"
        service.create_schedule(
            name=name,
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )

        found = service.get_schedule_by_name(name)
        assert found is not None
        assert found.name == name

    def test_get_schedules_by_type_right(self, service):
        """[Right] 타입별 스케줄 조회가 올바르게 동작해야 함."""
        # 여러 타입의 스케줄 생성
        ts = datetime.now().timestamp()
        service.create_schedule(
            name=f"ig1_{ts}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL,
            enabled=True
        )
        service.create_schedule(
            name=f"blog1_{ts}",
            target_type=CrawlSchedule.TARGET_TYPE_NAVER_BLOG,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL,
            enabled=True
        )

        ig_schedules = service.get_schedules_by_type(CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED)
        assert len(ig_schedules) >= 1
        for s in ig_schedules:
            assert s.target_type == CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED

    def test_update_schedule_right(self, service):
        """[Right] 스케줄 업데이트가 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"update_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL,
            enabled=True
        )

        updated = service.update_schedule(
            schedule.id,
            display_name="업데이트된 이름",
            enabled=False,
            target_config={"account_id": 2}
        )

        assert updated.display_name == "업데이트된 이름"
        assert updated.enabled == False
        assert updated.get_target_config()["account_id"] == 2

    def test_start_run_right(self, service):
        """[Right] 실행 시작이 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"run_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )

        run = service.start_run(
            schedule.id,
            worker_id="worker-123",
            config_snapshot={"max_posts": 100}
        )

        assert run.id is not None
        assert run.schedule_id == schedule.id
        assert run.status == CrawlScheduleRun.STATUS_RUNNING
        assert run.worker_id == "worker-123"
        assert run.get_config_snapshot()["max_posts"] == 100

    def test_complete_run_right(self, service):
        """[Right] 실행 완료가 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"complete_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )
        run = service.start_run(schedule.id)

        completed = service.complete_run(
            run.id,
            collected_count=100,
            saved_count=80,
            stop_reason=CrawlScheduleRun.STOP_REASON_DUPLICATE
        )

        assert completed.status == CrawlScheduleRun.STATUS_COMPLETED
        assert completed.collected_count == 100
        assert completed.saved_count == 80
        assert completed.stop_reason == CrawlScheduleRun.STOP_REASON_DUPLICATE
        assert completed.finished_at is not None

    def test_fail_run_right(self, service):
        """[Right] 실행 실패가 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"fail_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )
        run = service.start_run(schedule.id)

        failed = service.fail_run(run.id, "Login required")

        assert failed.status == CrawlScheduleRun.STATUS_FAILED
        assert failed.error_message == "Login required"

    def test_get_runs_paginated_right(self, service):
        """[Right] 실행 이력 페이징이 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"pagination_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )

        # 15개 실행 생성
        for i in range(15):
            run = service.start_run(schedule.id)
            service.complete_run(run.id, i * 10, i * 5)

        result = service.get_runs_paginated(schedule_id=schedule.id, page=1, limit=10)

        assert result["total"] == 15
        assert len(result["items"]) == 10
        assert result["pages"] == 2

    def test_get_run_stats_right(self, service):
        """[Right] 실행 통계가 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"stats_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )

        # 성공 2개, 실패 1개
        for i in range(2):
            run = service.start_run(schedule.id)
            service.complete_run(run.id, 100, 80)

        failed_run = service.start_run(schedule.id)
        service.fail_run(failed_run.id, "Error")

        stats = service.get_run_stats(schedule_id=schedule.id, days=1)

        assert stats["total_runs"] == 3
        assert stats["completed_runs"] == 2
        assert stats["failed_runs"] == 1
        assert stats["total_collected"] == 200
        assert stats["total_saved"] == 160

    def test_update_schedule_after_run_right(self, service):
        """[Right] 실행 후 스케줄 업데이트가 올바르게 동작해야 함."""
        schedule = service.create_schedule(
            name=f"after_run_test_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )

        assert schedule.last_run_at is None

        next_run = datetime.now() + timedelta(hours=3)
        service.update_schedule_after_run(schedule.id, next_run)

        # 다시 조회
        updated = service.get_schedule_by_id(schedule.id)
        assert updated.last_run_at is not None
        assert updated.next_run_at == next_run
