"""
크롤링 모델 테스트 (CrawlRequest, CrawlSchedule, CrawlScheduleRun)

RIGHT-BICEP 테스트 원칙 적용:
- Right: 올바른 결과 반환
- Boundary: 경계값 테스트
- Inverse: 역관계 테스트
- Cross-check: 다른 방법으로 검증
- Error: 예외 상황 처리
- Performance: 성능 (해당 시 적용)

CORRECT 원칙 적용:
- Conformance: 형식 준수
- Ordering: 순서
- Range: 범위
- Reference: 참조
- Existence: 존재
- Cardinality: 개수
- Time: 시간
"""

import pytest
import uuid
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from app.models import CrawlRequest, CrawlSchedule, CrawlScheduleRun


def unique_name(prefix: str = "test") -> str:
    """테스트용 고유 이름 생성."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestCrawlRequest:
    """CrawlRequest 모델 테스트."""

    def test_create_request_right(self, test_db_session):
        """[Right] 기본 요청 생성이 올바르게 동작해야 함."""
        request = CrawlRequest(
            url="https://www.instagram.com/p/ABC123/",
            url_type=CrawlRequest.URL_TYPE_INSTAGRAM,
            requested_by="manual"
        )
        test_db_session.add(request)
        test_db_session.commit()

        assert request.id is not None
        assert request.status == CrawlRequest.STATUS_PENDING
        assert request.retry_count == 0
        assert request.requested_at is not None

    def test_status_transition_right(self, test_db_session):
        """[Right] 상태 전환이 올바르게 동작해야 함."""
        request = CrawlRequest(
            url="https://example.com",
            url_type=CrawlRequest.URL_TYPE_OTHER
        )
        test_db_session.add(request)
        test_db_session.commit()

        # pending -> picked
        request.mark_picked("worker-123")
        assert request.status == CrawlRequest.STATUS_PICKED
        assert request.worker_id == "worker-123"
        assert request.picked_at is not None

        # picked -> processing
        request.mark_processing()
        assert request.status == CrawlRequest.STATUS_PROCESSING

        # processing -> completed
        request.mark_completed("crawled_page", 42)
        assert request.status == CrawlRequest.STATUS_COMPLETED
        assert request.result_type == "crawled_page"
        assert request.result_id == 42
        assert request.processed_at is not None

    def test_mark_failed_right(self, test_db_session):
        """[Right] 실패 처리가 올바르게 동작해야 함."""
        request = CrawlRequest(
            url="https://example.com",
            url_type=CrawlRequest.URL_TYPE_OTHER
        )
        test_db_session.add(request)
        test_db_session.commit()

        request.mark_failed("Connection timeout")
        assert request.status == CrawlRequest.STATUS_FAILED
        assert request.error_message == "Connection timeout"
        assert request.processed_at is not None

    def test_url_type_boundary(self, test_db_session):
        """[Boundary] 다양한 URL 타입이 저장되어야 함."""
        url_types = [
            CrawlRequest.URL_TYPE_INSTAGRAM,
            CrawlRequest.URL_TYPE_NAVER_BLOG,
            CrawlRequest.URL_TYPE_NAVER_FORM,
            CrawlRequest.URL_TYPE_GOOGLE_FORM,
            CrawlRequest.URL_TYPE_OTHER,
        ]

        for url_type in url_types:
            request = CrawlRequest(
                url=f"https://example.com/{url_type}",
                url_type=url_type
            )
            test_db_session.add(request)

        test_db_session.commit()

        # 모든 타입이 저장되었는지 확인
        count = test_db_session.query(CrawlRequest).count()
        assert count >= len(url_types)

    def test_url_required_existence(self, test_db_session):
        """[Existence] url과 url_type은 필수여야 함."""
        request = CrawlRequest(url_type=CrawlRequest.URL_TYPE_OTHER)
        test_db_session.add(request)

        with pytest.raises(IntegrityError):
            test_db_session.commit()

    def test_repr_conformance(self, test_db_session):
        """[Conformance] __repr__이 올바른 형식을 반환해야 함."""
        request = CrawlRequest(
            url="https://example.com",
            url_type=CrawlRequest.URL_TYPE_OTHER
        )
        test_db_session.add(request)
        test_db_session.commit()

        repr_str = repr(request)
        assert "CrawlRequest" in repr_str
        assert str(request.id) in repr_str
        assert request.url_type in repr_str
        assert request.status in repr_str


class TestCrawlSchedule:
    """CrawlSchedule 모델 테스트."""

    def test_create_schedule_right(self, test_db_session):
        """[Right] 기본 스케줄 생성이 올바르게 동작해야 함."""
        schedule = CrawlSchedule(
            name=unique_name("instagram_feed"),
            display_name="Instagram 피드 테스트",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value='{"times": ["09:00", "14:00", "21:00"]}',
            enabled=True
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        assert schedule.id is not None
        assert schedule.enabled == True
        assert schedule.created_at is not None

    def test_unique_name_constraint(self, test_db_session):
        """[Existence] name은 유니크해야 함."""
        dup_name = unique_name("duplicate")
        schedule1 = CrawlSchedule(
            name=dup_name,
            target_type="test",
            schedule_type="manual"
        )
        test_db_session.add(schedule1)
        test_db_session.commit()

        schedule2 = CrawlSchedule(
            name=dup_name,  # 중복
            target_type="test",
            schedule_type="manual"
        )
        test_db_session.add(schedule2)

        with pytest.raises(IntegrityError):
            test_db_session.commit()

        test_db_session.rollback()  # 실패한 트랜잭션 롤백

    def test_target_config_json_right(self, test_db_session):
        """[Right] target_config JSON 직렬화가 올바르게 동작해야 함."""
        name = unique_name("config")
        schedule = CrawlSchedule(
            name=name,
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_INTERVAL
        )

        config = {"account_id": 1, "max_posts": 500, "duplicate_stop": 5}
        schedule.set_target_config(config)
        test_db_session.add(schedule)
        test_db_session.commit()

        # DB에서 다시 로드
        loaded = test_db_session.query(CrawlSchedule).filter_by(name=name).first()
        assert loaded.get_target_config() == config

    def test_target_config_empty_boundary(self, test_db_session):
        """[Boundary] 빈 target_config 처리."""
        schedule = CrawlSchedule(
            name=unique_name("empty_config"),
            target_type="test",
            schedule_type="manual",
            target_config=None
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        assert schedule.get_target_config() == {}

    def test_update_last_run_time(self, test_db_session):
        """[Time] 마지막 실행 시간 업데이트가 올바르게 동작해야 함."""
        schedule = CrawlSchedule(
            name=unique_name("time"),
            target_type="test",
            schedule_type="manual"
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        assert schedule.last_run_at is None

        next_run = datetime.now() + timedelta(hours=1)
        schedule.update_last_run(next_run)

        assert schedule.last_run_at is not None
        assert schedule.next_run_at == next_run

    def test_runs_relationship_cardinality(self, test_db_session):
        """[Cardinality] 스케줄과 실행 이력의 1:N 관계."""
        schedule = CrawlSchedule(
            name=unique_name("cardinality"),
            target_type="test",
            schedule_type="manual"
        )
        test_db_session.add(schedule)
        test_db_session.commit()

        # 3개의 실행 이력 추가
        for i in range(3):
            run = CrawlScheduleRun(
                schedule_id=schedule.id,
                started_at=datetime.now(),
                status=CrawlScheduleRun.STATUS_COMPLETED
            )
            test_db_session.add(run)
        test_db_session.commit()

        # relationship으로 접근
        assert len(schedule.runs) == 3


class TestCrawlScheduleRun:
    """CrawlScheduleRun 모델 테스트."""

    @pytest.fixture
    def sample_schedule(self, test_db_session):
        """테스트용 스케줄 생성."""
        schedule = CrawlSchedule(
            name=f"test_schedule_{datetime.now().timestamp()}",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_MANUAL
        )
        test_db_session.add(schedule)
        test_db_session.commit()
        return schedule

    def test_create_run_right(self, test_db_session, sample_schedule):
        """[Right] 기본 실행 기록 생성이 올바르게 동작해야 함."""
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now(),
            worker_id="worker-123"
        )
        test_db_session.add(run)
        test_db_session.commit()

        assert run.id is not None
        assert run.status == CrawlScheduleRun.STATUS_RUNNING
        assert run.collected_count == 0
        assert run.saved_count == 0

    def test_mark_completed_right(self, test_db_session, sample_schedule):
        """[Right] 완료 처리가 올바르게 동작해야 함."""
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now()
        )
        test_db_session.add(run)
        test_db_session.commit()

        run.mark_completed(
            collected_count=100,
            saved_count=50,
            stop_reason=CrawlScheduleRun.STOP_REASON_DUPLICATE
        )

        assert run.status == CrawlScheduleRun.STATUS_COMPLETED
        assert run.collected_count == 100
        assert run.saved_count == 50
        assert run.stop_reason == CrawlScheduleRun.STOP_REASON_DUPLICATE
        assert run.finished_at is not None

    def test_mark_failed_right(self, test_db_session, sample_schedule):
        """[Right] 실패 처리가 올바르게 동작해야 함."""
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now()
        )
        test_db_session.add(run)
        test_db_session.commit()

        run.mark_failed("Login required")

        assert run.status == CrawlScheduleRun.STATUS_FAILED
        assert run.error_message == "Login required"
        assert run.finished_at is not None

    def test_duration_seconds_time(self, test_db_session, sample_schedule):
        """[Time] 실행 시간 계산이 올바르게 동작해야 함."""
        start = datetime.now()
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=start
        )
        test_db_session.add(run)
        test_db_session.commit()

        # 완료 전에는 None
        assert run.duration_seconds is None

        # 완료 후 계산
        run.finished_at = start + timedelta(seconds=120)
        assert run.duration_seconds == 120

    def test_config_snapshot_json_right(self, test_db_session, sample_schedule):
        """[Right] config_snapshot JSON 직렬화가 올바르게 동작해야 함."""
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now()
        )

        config = {"max_posts": 500, "duplicate_stop": 5}
        run.set_config_snapshot(config)
        test_db_session.add(run)
        test_db_session.commit()

        loaded = test_db_session.query(CrawlScheduleRun).get(run.id)
        assert loaded.get_config_snapshot() == config

    def test_schedule_foreign_key_reference(self, test_db_session, sample_schedule):
        """[Reference] 스케줄 FK 관계가 올바르게 동작해야 함."""
        run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now()
        )
        test_db_session.add(run)
        test_db_session.commit()

        # relationship으로 접근
        assert run.schedule.id == sample_schedule.id
        assert run.schedule.name == sample_schedule.name

    def test_retry_self_reference(self, test_db_session, sample_schedule):
        """[Reference] 재시도 자기참조 FK가 올바르게 동작해야 함."""
        original_run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_FAILED,
            error_message="First attempt failed"
        )
        test_db_session.add(original_run)
        test_db_session.commit()

        retry_run = CrawlScheduleRun(
            schedule_id=sample_schedule.id,
            started_at=datetime.now(),
            retry_count=1,
            retry_of_run_id=original_run.id
        )
        test_db_session.add(retry_run)
        test_db_session.commit()

        assert retry_run.retry_of.id == original_run.id
        assert retry_run.retry_count == 1

    def test_cascade_delete_ordering(self, test_db_session):
        """[Ordering] 스케줄 삭제 시 실행 기록도 삭제되어야 함."""
        schedule = CrawlSchedule(
            name=f"cascade_test_{datetime.now().timestamp()}",
            target_type="test",
            schedule_type="manual"
        )
        test_db_session.add(schedule)
        test_db_session.commit()
        schedule_id = schedule.id

        # 실행 기록 추가
        run = CrawlScheduleRun(
            schedule_id=schedule_id,
            started_at=datetime.now()
        )
        test_db_session.add(run)
        test_db_session.commit()
        run_id = run.id

        # 스케줄 삭제
        test_db_session.delete(schedule)
        test_db_session.commit()

        # 실행 기록도 삭제되었는지 확인
        deleted_run = test_db_session.query(CrawlScheduleRun).get(run_id)
        assert deleted_run is None


class TestCrawlModelsIntegration:
    """모델 간 통합 테스트."""

    def test_full_crawl_workflow(self, test_db_session):
        """[Cross-check] 전체 크롤링 워크플로우 테스트."""
        # 1. 스케줄 생성
        schedule = CrawlSchedule(
            name=f"workflow_test_{datetime.now().timestamp()}",
            display_name="워크플로우 테스트",
            target_type=CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value='{"times": ["09:00"]}',
            enabled=True
        )
        schedule.set_target_config({"account_id": 1})
        test_db_session.add(schedule)
        test_db_session.commit()

        # 2. 실행 시작
        run = CrawlScheduleRun(
            schedule_id=schedule.id,
            started_at=datetime.now(),
            worker_id="worker-001"
        )
        run.set_config_snapshot(schedule.get_target_config())
        test_db_session.add(run)
        test_db_session.commit()

        # 3. 실행 완료
        run.mark_completed(
            collected_count=100,
            saved_count=80,
            stop_reason=CrawlScheduleRun.STOP_REASON_DUPLICATE
        )
        schedule.update_last_run(datetime.now() + timedelta(hours=5))
        test_db_session.commit()

        # 4. 검증
        assert schedule.last_run_at is not None
        assert len(schedule.runs) == 1
        assert schedule.runs[0].status == CrawlScheduleRun.STATUS_COMPLETED
        assert schedule.runs[0].saved_count == 80

    def test_single_request_workflow(self, test_db_session):
        """[Cross-check] 단건 요청 워크플로우 테스트."""
        # 1. 요청 생성
        request = CrawlRequest(
            url="https://www.instagram.com/p/TEST123/",
            url_type=CrawlRequest.URL_TYPE_INSTAGRAM,
            requested_by="manual"
        )
        test_db_session.add(request)
        test_db_session.commit()

        # 2. 워커가 픽업
        request.mark_picked("worker-002")
        test_db_session.commit()

        # 3. 처리 시작
        request.mark_processing()
        test_db_session.commit()

        # 4. 완료
        request.mark_completed("instagram_post", 999)
        test_db_session.commit()

        # 5. 검증
        loaded = test_db_session.query(CrawlRequest).get(request.id)
        assert loaded.status == CrawlRequest.STATUS_COMPLETED
        assert loaded.result_type == "instagram_post"
        assert loaded.result_id == 999
        assert loaded.worker_id == "worker-002"
        assert loaded.picked_at is not None
        assert loaded.processed_at is not None
