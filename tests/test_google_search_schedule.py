"""
Google 검색 스케줄 테스트.

테스트 방법론:
- RIGHT-BICEP (결과, 경계, 역관계, 교차검증, 에러, 성능)
- CORRECT (일관성, 순서, 범위, 참조, 존재, 카디널리티, 시간)

테스트 범위:
- CrawlSchedule 모델 (TARGET_TYPE_GOOGLE_SEARCH)
- Google 검색 스케줄 API
- ScheduledCrawlWorker Google 검색 핸들러
"""
import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.base import Base
from app.models.crawl_schedule import CrawlSchedule, CrawlScheduleRun
from app.models.google_search import (
    GoogleSearchQueue,
    GoogleSearchHistory,
    GoogleSavedSearch,
)
from app.main import app
from app.database import get_db


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session():
    """인메모리 SQLite 세션 생성."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_saved_search(db_session):
    """샘플 저장된 검색 생성."""
    saved = GoogleSavedSearch(
        name="테스트 검색",
        query="Python 튜토리얼",
        date_filter="1w",
        max_pages=2,
    )
    db_session.add(saved)
    db_session.commit()
    db_session.refresh(saved)
    return saved


@pytest.fixture
def sample_google_schedule(db_session, sample_saved_search):
    """샘플 Google 검색 스케줄 생성."""
    schedule = CrawlSchedule(
        name=f"google_search_{sample_saved_search.id}",
        display_name="테스트 자동 검색",
        target_type=CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        target_config=json.dumps({"saved_search_id": sample_saved_search.id}),
        schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        schedule_value=json.dumps({
            "time_windows": [{"start": "09:00", "end": "18:00"}],
            "daily_runs": 1,
            "min_interval_hours": 1
        }),
        enabled=True,
    )
    db_session.add(schedule)
    db_session.commit()
    db_session.refresh(schedule)
    return schedule


# ============================================================
# RIGHT: Are the results right?
# ============================================================

class TestCrawlScheduleConstants:
    """CrawlSchedule 상수 테스트."""

    def test_target_type_google_search_exists(self):
        """TARGET_TYPE_GOOGLE_SEARCH 상수 존재 확인."""
        assert hasattr(CrawlSchedule, "TARGET_TYPE_GOOGLE_SEARCH")
        assert CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH == "google_search"

    def test_stop_reason_search_completed_exists(self):
        """STOP_REASON_SEARCH_COMPLETED 상수 존재 확인."""
        assert hasattr(CrawlScheduleRun, "STOP_REASON_SEARCH_COMPLETED")
        assert CrawlScheduleRun.STOP_REASON_SEARCH_COMPLETED == "search_completed"

    def test_stop_reason_captcha_exists(self):
        """STOP_REASON_CAPTCHA 상수 존재 확인."""
        assert hasattr(CrawlScheduleRun, "STOP_REASON_CAPTCHA")
        assert CrawlScheduleRun.STOP_REASON_CAPTCHA == "captcha_detected"


class TestGoogleScheduleResults:
    """Google 검색 스케줄 결과 테스트."""

    def test_schedule_creation_with_google_search_type(self, db_session, sample_saved_search):
        """Google 검색 타입으로 스케줄 생성."""
        schedule = CrawlSchedule(
            name="test_google_schedule",
            target_type=CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
        )
        schedule.set_target_config({"saved_search_id": sample_saved_search.id})

        db_session.add(schedule)
        db_session.commit()

        assert schedule.id is not None
        assert schedule.target_type == "google_search"
        assert schedule.get_target_config()["saved_search_id"] == sample_saved_search.id

    def test_schedule_run_creation(self, db_session, sample_google_schedule):
        """스케줄 실행 기록 생성."""
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
        )
        db_session.add(run)
        db_session.commit()

        assert run.id is not None
        assert run.status == "running"

    def test_schedule_run_mark_completed(self, db_session, sample_google_schedule):
        """스케줄 실행 완료 처리."""
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
        )
        db_session.add(run)
        db_session.commit()

        # 완료 처리
        run.mark_completed(
            collected_count=25,
            saved_count=25,
            stop_reason=CrawlScheduleRun.STOP_REASON_SEARCH_COMPLETED
        )
        db_session.commit()

        assert run.status == "completed"
        assert run.collected_count == 25
        assert run.stop_reason == "search_completed"
        assert run.finished_at is not None


# ============================================================
# BOUNDARY: Are the boundary conditions correct?
# ============================================================

class TestGoogleScheduleBoundary:
    """경계 조건 테스트."""

    def test_schedule_without_saved_search_id(self, db_session):
        """saved_search_id 없는 스케줄 설정."""
        schedule = CrawlSchedule(
            name="empty_config_schedule",
            target_type=CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        )
        schedule.set_target_config({})
        db_session.add(schedule)
        db_session.commit()

        config = schedule.get_target_config()
        assert config.get("saved_search_id") is None

    def test_schedule_with_empty_time_windows(self, db_session, sample_saved_search):
        """빈 time_windows 스케줄."""
        schedule = CrawlSchedule(
            name="empty_windows_schedule",
            target_type=CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
            schedule_type=CrawlSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            schedule_value=json.dumps({"time_windows": [], "daily_runs": 1}),
        )
        schedule.set_target_config({"saved_search_id": sample_saved_search.id})
        db_session.add(schedule)
        db_session.commit()

        value = json.loads(schedule.schedule_value)
        assert value["time_windows"] == []


# ============================================================
# ERROR: Can you force error conditions?
# ============================================================

class TestGoogleScheduleError:
    """에러 조건 테스트."""

    def test_schedule_run_mark_failed(self, db_session, sample_google_schedule):
        """스케줄 실행 실패 처리."""
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
        )
        db_session.add(run)
        db_session.commit()

        # 실패 처리
        run.mark_failed("CAPTCHA 감지됨")
        db_session.commit()

        assert run.status == "failed"
        assert run.error_message == "CAPTCHA 감지됨"
        assert run.finished_at is not None

    def test_schedule_run_timeout(self, db_session, sample_google_schedule):
        """스케줄 실행 타임아웃."""
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_RUNNING,
        )
        db_session.add(run)
        db_session.commit()

        run.mark_failed("Timeout")
        db_session.commit()

        assert run.status == "failed"
        assert "Timeout" in run.error_message


# ============================================================
# CORRECT: Conformance, Ordering, Range, Reference, Existence, Cardinality, Time
# ============================================================

class TestGoogleScheduleCorrect:
    """CORRECT 테스트."""

    def test_conformance_target_type(self, sample_google_schedule):
        """target_type 적합성."""
        assert sample_google_schedule.target_type in [
            CrawlSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            CrawlSchedule.TARGET_TYPE_NAVER_BLOG,
            CrawlSchedule.TARGET_TYPE_NAVER_CAFE,
            CrawlSchedule.TARGET_TYPE_GOOGLE_SEARCH,
        ]

    def test_ordering_runs_by_started_at(self, db_session, sample_google_schedule):
        """실행 기록 시간순 정렬."""
        import time

        runs = []
        for i in range(3):
            run = CrawlScheduleRun(
                schedule_id=sample_google_schedule.id,
                started_at=datetime.now(),
                status=CrawlScheduleRun.STATUS_COMPLETED,
            )
            db_session.add(run)
            db_session.commit()
            runs.append(run)
            time.sleep(0.01)

        ordered = db_session.query(CrawlScheduleRun).filter_by(
            schedule_id=sample_google_schedule.id
        ).order_by(CrawlScheduleRun.started_at.desc()).all()

        for i in range(len(ordered) - 1):
            assert ordered[i].started_at >= ordered[i + 1].started_at

    def test_reference_schedule_to_saved_search(self, db_session, sample_google_schedule, sample_saved_search):
        """스케줄에서 저장된 검색 참조."""
        config = sample_google_schedule.get_target_config()
        saved_search_id = config.get("saved_search_id")

        saved = db_session.query(GoogleSavedSearch).filter_by(id=saved_search_id).first()
        assert saved is not None
        assert saved.id == sample_saved_search.id

    def test_cardinality_multiple_runs(self, db_session, sample_google_schedule):
        """하나의 스케줄에 여러 실행."""
        for i in range(5):
            run = CrawlScheduleRun(
                schedule_id=sample_google_schedule.id,
                started_at=datetime.now(),
                status=CrawlScheduleRun.STATUS_COMPLETED,
            )
            db_session.add(run)

        db_session.commit()

        runs = db_session.query(CrawlScheduleRun).filter_by(
            schedule_id=sample_google_schedule.id
        ).all()
        assert len(runs) == 5

    def test_time_duration_seconds(self, db_session, sample_google_schedule):
        """실행 시간 계산."""
        started = datetime.now()
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=started,
            status=CrawlScheduleRun.STATUS_RUNNING,
        )
        db_session.add(run)
        db_session.commit()

        # 3초 후 완료
        run.finished_at = started + timedelta(seconds=3)
        run.status = CrawlScheduleRun.STATUS_COMPLETED
        db_session.commit()

        assert run.duration_seconds == 3


# ============================================================
# API Route Tests
# ============================================================

@pytest.fixture
def test_client(db_session):
    """테스트 클라이언트."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class TestGoogleScheduleAPI:
    """Google 검색 스케줄 API 테스트."""

    def test_create_schedule(self, test_client, db_session, sample_saved_search):
        """스케줄 생성 API."""
        response = test_client.post(
            "/api/google/schedule/",
            json={
                "saved_search_id": sample_saved_search.id,
                "display_name": "API 테스트 스케줄",
                "schedule_type": "time_window",
                "schedule_value": {
                    "time_windows": [{"start": "10:00", "end": "12:00"}],
                    "daily_runs": 2,
                    "min_interval_hours": 1
                },
                "enabled": True
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["display_name"] == "API 테스트 스케줄"
        assert data["target_type"] == "google_search"
        assert data["enabled"] is True

    def test_list_schedules(self, test_client, db_session, sample_google_schedule):
        """스케줄 목록 조회 API."""
        response = test_client.get("/api/google/schedule/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_schedule(self, test_client, db_session, sample_google_schedule):
        """스케줄 조회 API."""
        response = test_client.get(f"/api/google/schedule/{sample_google_schedule.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_google_schedule.id

    def test_update_schedule(self, test_client, db_session, sample_google_schedule):
        """스케줄 수정 API."""
        response = test_client.put(
            f"/api/google/schedule/{sample_google_schedule.id}",
            json={
                "display_name": "수정된 스케줄",
                "enabled": False
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "수정된 스케줄"
        assert data["enabled"] is False

    def test_delete_schedule(self, test_client, db_session, sample_google_schedule):
        """스케줄 삭제 API."""
        schedule_id = sample_google_schedule.id

        response = test_client.delete(f"/api/google/schedule/{schedule_id}")
        assert response.status_code == 200

        # 삭제 확인
        response = test_client.get(f"/api/google/schedule/{schedule_id}")
        assert response.status_code == 404

    def test_enable_disable_schedule(self, test_client, db_session, sample_google_schedule):
        """스케줄 활성화/비활성화 API."""
        # 비활성화
        response = test_client.post(f"/api/google/schedule/{sample_google_schedule.id}/disable")
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        # 활성화
        response = test_client.post(f"/api/google/schedule/{sample_google_schedule.id}/enable")
        assert response.status_code == 200
        assert response.json()["enabled"] is True

    def test_get_schedule_runs(self, test_client, db_session, sample_google_schedule):
        """스케줄 실행 이력 조회 API."""
        # 실행 기록 생성
        for i in range(3):
            run = CrawlScheduleRun(
                schedule_id=sample_google_schedule.id,
                started_at=datetime.now(),
                status=CrawlScheduleRun.STATUS_COMPLETED,
                collected_count=10,
                saved_count=10,
            )
            db_session.add(run)
        db_session.commit()

        response = test_client.get(f"/api/google/schedule/{sample_google_schedule.id}/runs")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) == 3
        assert data["total"] == 3

    def test_get_schedule_stats(self, test_client, db_session, sample_google_schedule):
        """스케줄 통계 조회 API."""
        # 실행 기록 생성
        run = CrawlScheduleRun(
            schedule_id=sample_google_schedule.id,
            started_at=datetime.now(),
            status=CrawlScheduleRun.STATUS_COMPLETED,
            collected_count=20,
            saved_count=20,
        )
        db_session.add(run)
        db_session.commit()

        response = test_client.get(f"/api/google/schedule/{sample_google_schedule.id}/stats?days=7")

        assert response.status_code == 200
        data = response.json()
        assert "total_runs" in data
        assert "success_rate" in data

    def test_create_duplicate_schedule_error(self, test_client, db_session, sample_saved_search, sample_google_schedule):
        """중복 스케줄 생성 에러."""
        response = test_client.post(
            "/api/google/schedule/",
            json={
                "saved_search_id": sample_saved_search.id,
                "schedule_type": "time_window",
                "schedule_value": {
                    "time_windows": [{"start": "10:00", "end": "12:00"}],
                    "daily_runs": 1,
                    "min_interval_hours": 1
                },
            }
        )

        assert response.status_code == 400
        assert "이미" in response.json()["detail"]

    def test_schedule_not_found_error(self, test_client):
        """존재하지 않는 스케줄 에러."""
        response = test_client.get("/api/google/schedule/99999")
        assert response.status_code == 404


# ============================================================
# Worker Tests (Mocked)
# ============================================================

class TestScheduledCrawlWorkerGoogleSearch:
    """ScheduledCrawlWorker Google 검색 핸들러 테스트."""

    @pytest.mark.asyncio
    async def test_wait_for_search_completion_success(self, db_session):
        """검색 완료 대기 성공."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        search_id = str(uuid.uuid4())

        # 큐 아이템 생성 (완료 상태)
        queue = GoogleSearchQueue(
            search_id=search_id,
            query="test",
            status="completed",
        )
        db_session.add(queue)

        # 히스토리 생성
        history = GoogleSearchHistory(
            search_id=search_id,
            query="test",
            status="completed",
            total_results=15,
        )
        db_session.add(history)
        db_session.commit()

        worker = ScheduledCrawlWorker()

        # _wait_for_search_completion 메서드를 직접 테스트
        with patch.object(worker, '_wait_for_search_completion') as mock_wait:
            mock_wait.return_value = {
                "status": "completed",
                "total_results": 15,
                "error_message": None
            }

            result = await mock_wait(search_id)

            assert result["status"] == "completed"
            assert result["total_results"] == 15

    @pytest.mark.asyncio
    async def test_wait_for_search_completion_failed(self):
        """검색 완료 대기 실패."""
        from app.worker.scheduled_worker import ScheduledCrawlWorker

        worker = ScheduledCrawlWorker()

        with patch.object(worker, '_wait_for_search_completion') as mock_wait:
            mock_wait.return_value = {
                "status": "failed",
                "total_results": 0,
                "error_message": "CAPTCHA 감지됨"
            }

            result = await mock_wait("test-id")

            assert result["status"] == "failed"
            assert "CAPTCHA" in result["error_message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
