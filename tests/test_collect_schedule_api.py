"""
수집 스케줄(Collect Schedule) API 테스트

RIGHT-BICEP 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 테스트
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트

테스트 대상:
- POST /api/v1f"{API_PREFIX}/collect/schedules" - 스케줄 생성
- GET /api/v1f"{API_PREFIX}/collect/schedules" - 스케줄 목록 조회
- POST /api/v1f"{API_PREFIX}/collect/schedules"/{id}/toggle - 스케줄 토글
- POST /api/v1f"{API_PREFIX}/collect/schedules"/{id}/run - 스케줄 즉시 실행
"""

# API Prefix
API_PREFIX = "/api/v1"

import pytest
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.base import Base
from app.models import TaskSchedule, TaskScheduleRun, ServiceAccount, BrowserProfile
from app.models.google_search import GoogleSavedSearch, GoogleSearchQueue
from app.routes.collect import router as collect_router

pytestmark = pytest.mark.http


# ============================================================
# 테스트용 DB 설정
# ============================================================

@pytest.fixture(scope="function")
def test_db():
    """테스트용 인메모리 DB"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 테이블 생성 — postgresql.UUID 컬럼이 있는 테이블은 SQLite에서 실패하므로
    # 스케줄 API 테스트에 필요한 테이블만 명시적으로 생성
    _NEEDED = {
        "task_schedules", "task_schedule_runs",
        "crawl_requests",
        "service_accounts", "browser_profiles",
        "google_saved_searches",
        "google_search_queue",
    }
    tables = [t for name, t in Base.metadata.tables.items() if name in _NEEDED]
    Base.metadata.create_all(bind=engine, tables=tables)

    session = TestingSessionLocal()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def client(test_db):
    """테스트용 FastAPI 클라이언트"""
    app = FastAPI()
    app.include_router(collect_router, prefix="/api/v1")

    routes = {route.path for route in app.routes}
    assert "/api/v1/collect/schedules/{schedule_id}/run" in routes

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_browser_profile(test_db):
    """테스트용 브라우저 프로필"""
    profile = BrowserProfile(
        name="테스트 프로필",
        profile_dir="test_profile_dir",
    )
    test_db.add(profile)
    test_db.commit()
    test_db.refresh(profile)
    return profile


@pytest.fixture
def sample_service_account(test_db, sample_browser_profile):
    """테스트용 Instagram 서비스 계정"""
    account = ServiceAccount(
        profile_id=sample_browser_profile.id,
        service_type="instagram",
        identifier="test_user",
        is_logged_in=True,
    )
    test_db.add(account)
    test_db.commit()
    test_db.refresh(account)
    return account


@pytest.fixture
def sample_saved_search(test_db):
    """테스트용 Google 저장된 검색"""
    saved = GoogleSavedSearch(
        name="테스트 검색",
        query="test query",
        date_filter="w",
        max_pages=3,
        is_favorite=False,
    )
    test_db.add(saved)
    test_db.commit()
    test_db.refresh(saved)
    return saved


# ============================================================
# Right: 올바른 결과 테스트
# ============================================================

class TestCreateScheduleRight:
    """스케줄 생성 API - 올바른 결과 테스트"""

    def test_create_instagram_schedule_success(self, client, sample_service_account):
        """Instagram 스케줄 생성 성공"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
            "schedule_type": "time_window",
            "schedule_value": {
                "daily_runs": 3,
                "time_windows": [
                    {"start": "09:00", "end": "12:00"},
                    {"start": "12:00", "end": "15:00"},
                    {"start": "18:00", "end": "21:00"},
                ]
            }
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "instagram_feed"
        assert data["enabled"] is True
        assert "Instagram 피드" in data["display_name"]

    def test_create_google_schedule_success(self, client, sample_saved_search):
        """Google 검색 스케줄 생성 성공"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "google_search",
            "target_config": {"saved_search_id": sample_saved_search.id},
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []}
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "google_search"
        assert "Google 검색" in data["display_name"]

    def test_create_writing_schedule_success(self, client):
        """글쓰기 스케줄 생성 성공"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []}
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "writing_task"
        assert data["display_name"] == "글쓰기 태스크"

    def test_create_pytest_schedule_success(self, client):
        """pytest_run 스케줄 생성 성공"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "pytest_run",
            "target_config": {
                "test_path": "tests/",
                "extra_args": ["-q"],
                "auto_fix_plan": True,
                "llm_provider": "claude",
                "llm_model": "",
            },
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "pytest_run"
        assert data["display_name"] == "pytest 자동 실행"

    def test_create_plan_archive_schedule_success(self, client):
        """plan_archive_analyze 스케줄 생성 성공."""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "plan_archive_analyze",
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []},
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "plan_archive_analyze"
        assert data["enabled"] is True
        assert data["display_name"] == "Plan Archive LLM 분석"

    def test_create_devguide_staleness_schedule_success(self, client):
        """devguide_staleness 스케줄 생성 성공."""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "devguide_staleness",
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []},
        })

        assert response.status_code == 200
        data = response.json()
        assert data["target_type"] == "devguide_staleness"
        assert data["enabled"] is True
        assert data["display_name"] == "Dev-Guide 갱신 점검"


class TestGetSchedules:
    """스케줄 목록 조회 테스트"""

    def test_get_schedules_empty(self, client):
        """빈 스케줄 목록 조회"""
        response = client.get(f"{API_PREFIX}/collect/schedules")

        assert response.status_code == 200
        assert response.json() == []

    def test_get_schedules_with_data(self, client, sample_service_account):
        """스케줄 생성 후 목록 조회"""
        # 스케줄 생성
        client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })

        response = client.get(f"{API_PREFIX}/collect/schedules")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["target_type"] == "instagram_feed"


# ============================================================
# Error: 에러 조건 테스트
# ============================================================

class TestCreateScheduleErrors:
    """스케줄 생성 API - 에러 테스트"""

    def test_create_instagram_without_account_id(self, client):
        """Instagram 스케줄 - service_account_id 누락"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {},
        })

        assert response.status_code == 400
        assert "service_account_id" in response.json()["detail"]

    def test_create_google_without_saved_search_id(self, client):
        """Google 스케줄 - saved_search_id 누락"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "google_search",
            "target_config": {},
        })

        assert response.status_code == 400
        assert any(
            needle in response.json()["detail"]
            for needle in ("saved_search_id", "target_config")
        )

    def test_create_duplicate_plan_archive_schedule_error(self, client):
        """plan_archive_analyze 스케줄 중복 생성 시 400 반환."""
        payload = {
            "target_type": "plan_archive_analyze",
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []},
        }
        # 첫 번째 생성
        r1 = client.post(f"{API_PREFIX}/collect/schedules", json=payload)
        assert r1.status_code == 200

        # 두 번째 생성 — 중복
        r2 = client.post(f"{API_PREFIX}/collect/schedules", json=payload)
        assert r2.status_code == 400
        assert "이미 plan archive 분석 스케줄이 존재합니다" in r2.json()["detail"]

    def test_create_google_with_nonexistent_saved_search(self, client):
        """Google 스케줄 - 존재하지 않는 저장된 검색"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "google_search",
            "target_config": {"saved_search_id": 99999},
        })

        assert response.status_code == 404
        assert "저장된 검색을 찾을 수 없습니다" in response.json()["detail"]

    def test_create_unsupported_type(self, client):
        """지원하지 않는 스케줄 타입"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "unsupported_type",
        })

        assert response.status_code == 400
        assert "지원하지 않는" in response.json()["detail"]

    def test_create_duplicate_instagram_schedule(self, client, sample_service_account):
        """Instagram 스케줄 중복 생성 방지"""
        # 첫 번째 생성
        client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })

        # 두 번째 생성 시도
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })

        assert response.status_code == 400
        assert "이미" in response.json()["detail"]

    def test_create_duplicate_writing_schedule(self, client):
        """글쓰기 스케줄 중복 생성 방지"""
        # 첫 번째 생성
        client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
        })

        # 두 번째 생성 시도
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
        })

        assert response.status_code == 400
        assert "이미" in response.json()["detail"]


# ============================================================
# Toggle 테스트
# ============================================================

class TestToggleSchedule:
    """스케줄 활성화/비활성화 테스트"""

    def test_toggle_schedule_disable(self, client, sample_service_account):
        """스케줄 비활성화"""
        # 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })
        schedule_id = create_resp.json()["id"]

        # 비활성화
        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/toggle?enabled=false")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["enabled"] is False

    def test_toggle_nonexistent_schedule(self, client):
        """존재하지 않는 스케줄 토글"""
        response = client.post(f"{API_PREFIX}/collect/schedules/99999/toggle?enabled=false")

        assert response.status_code == 404


# ============================================================
# Run 테스트 (즉시 실행)
# ============================================================

class TestRunSchedule:
    """스케줄 즉시 실행 테스트"""

    def test_run_instagram_schedule(self, client, sample_service_account):
        """Instagram 스케줄 즉시 실행"""
        # 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })
        schedule_id = create_resp.json()["id"]

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "request_id" in data

    def test_run_writing_schedule(self, client, test_db):
        """글쓰기 스케줄 즉시 실행 — manual-run snapshot까지 검증"""
        schedule_id = _seed_run_supported_schedule(
            test_db,
            TaskSchedule.TARGET_TYPE_WRITING_TASK,
            "글쓰기 태스크",
        )

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "run_id" in data
        run = test_db.query(TaskScheduleRun).filter_by(id=data["run_id"]).one()
        assert run.schedule_id == schedule_id
        assert run.worker_id == "manual"
        assert run.status == TaskScheduleRun.STATUS_RUNNING
        assert run.get_config_snapshot() == {"source": "manual"}

    def test_run_topic_extract_schedule_creates_manual_run_http(self, client, test_db):
        """topic_extract 즉시 실행은 manual run을 생성한다."""
        schedule_id = _seed_run_supported_schedule(
            test_db,
            TaskSchedule.TARGET_TYPE_TOPIC_EXTRACT,
            "소재 추출 태스크",
        )

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        run = test_db.query(TaskScheduleRun).filter_by(id=data["run_id"]).one()
        assert run.schedule_id == schedule_id
        assert run.worker_id == "manual"
        assert run.status == TaskScheduleRun.STATUS_RUNNING
        assert run.get_config_snapshot() == {"source": "manual"}

    def test_run_google_schedule_uses_shared_enqueue_helper(self, client, test_db, sample_saved_search):
        """Google 즉시 실행이 공통 enqueue helper를 거쳐 search_id를 반환한다."""
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "google_search",
            "target_config": {"saved_search_id": sample_saved_search.id},
            "schedule_type": "time_window",
            "schedule_value": {"daily_runs": 1, "time_windows": []},
        })
        assert create_resp.status_code == 200
        schedule_id = create_resp.json()["id"]

        with patch(
            "app.routes.collect.enqueue_google_search",
            AsyncMock(return_value=GoogleSearchQueue.STATUS_QUEUED),
        ) as enqueue_mock:
            response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["search_id"]

        queue_item = (
            test_db.query(GoogleSearchQueue)
            .filter_by(search_id=data["search_id"])
            .first()
        )
        assert queue_item is not None
        assert queue_item.schedule_id == schedule_id
        assert queue_item.saved_search_id == sample_saved_search.id
        enqueue_mock.assert_awaited_once_with(queue_item, test_db)

    def test_run_plan_archive_schedule_returns_config_snapshot_patch(self, client):
        """plan_archive_analyze manual run returns queued/skipped stats."""
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "plan_archive_analyze",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:10"},
            "target_config": {"max_backfill_per_run": 5},
        })
        assert create_resp.status_code == 200
        schedule_id = create_resp.json()["id"]

        stats = {
            "queued": 2,
            "skipped_temp": 1,
            "skipped_empty": 0,
            "skipped_active_request": 1,
            "remaining_real_unprocessed": 3,
        }
        with patch(
            "app.routes.collect.PlanArchiveScheduler._enqueue_unprocessed_plans_in_session",
            return_value=stats,
        ) as enqueue_mock:
            response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["config_snapshot_patch"] == stats
        assert "queued 2" in data["message"]
        enqueue_mock.assert_called_once()
        assert enqueue_mock.call_args.kwargs["target_config"] == {"max_backfill_per_run": 5}

    def test_run_writing_source_schedule_creates_manual_run(self, client, test_db):
        """writing_source_collect 즉시 실행은 manual run을 생성한다."""
        schedule_id = _seed_run_supported_schedule(
            test_db,
            TaskSchedule.TARGET_TYPE_WRITING_SOURCE_COLLECT,
            "소스 수집 태스크",
        )

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        run = test_db.query(TaskScheduleRun).filter_by(id=data["run_id"]).one()
        assert run.schedule_id == schedule_id
        assert run.worker_id == "manual"
        assert run.status == TaskScheduleRun.STATUS_RUNNING
        assert run.get_config_snapshot() == {"source": "manual"}

    def test_run_keyword_analysis_schedule_creates_manual_run(self, client, test_db):
        """keyword_analysis 즉시 실행은 manual run을 생성한다."""
        schedule_id = _seed_run_supported_schedule(
            test_db,
            TaskSchedule.TARGET_TYPE_KEYWORD_ANALYSIS,
            "키워드 분석 태스크",
        )

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        run = test_db.query(TaskScheduleRun).filter_by(id=data["run_id"]).one()
        assert run.schedule_id == schedule_id
        assert run.worker_id == "manual"
        assert run.status == TaskScheduleRun.STATUS_RUNNING
        assert run.get_config_snapshot() == {"source": "manual"}

    def test_run_nonexistent_schedule(self, client):
        """존재하지 않는 스케줄 실행"""
        response = client.post(f"{API_PREFIX}/collect/schedules/99999/run")

        assert response.status_code == 404


class TestCollectHistoryWritingFailure:
    """GET /collect/history - writing 실패 진단 메타 검증"""

    def _seed_failed_writing_run(self, test_db) -> tuple[TaskSchedule, TaskScheduleRun]:
        schedule = TaskSchedule(
            name="writing_task_history_test",
            display_name="글쓰기 이력 테스트",
            target_type="writing_task",
            schedule_type="time_window",
            enabled=True,
        )
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)

        run = TaskScheduleRun(
            schedule_id=schedule.id,
            status=TaskScheduleRun.STATUS_FAILED,
            started_at=datetime(2026, 4, 20, 9, 19, 0),
            finished_at=datetime(2026, 4, 20, 9, 19, 0),
            error_message="소스 글이 부족합니다: 0개 (최소 3개 필요) - writing_sources 데이터 이관/동기화 누락을 확인하세요.",
            stop_reason="source_shortage",
        )
        test_db.add(run)
        test_db.commit()
        test_db.refresh(run)
        return schedule, run

    def test_collect_history_writing_failure_right(self, client, test_db):
        """TC-Right: writing 실패 run은 source_type=writing row로 반환된다."""
        schedule, run = self._seed_failed_writing_run(test_db)

        response = client.get(
            f"{API_PREFIX}/collect/history?source_type=writing&status=failed&period=month"
        )

        assert response.status_code == 200
        items = response.json()["items"]
        found = next((item for item in items if item["id"] == run.id), None)
        assert found is not None
        assert found["history_type"] == "schedule_run"
        assert found["source_type"] == "writing"
        assert found["schedule_id"] == schedule.id

    def test_collect_history_writing_failure_returns_error_message(self, client, test_db):
        """TC-Right: writing 실패 row는 error_message를 그대로 유지한다."""
        _, run = self._seed_failed_writing_run(test_db)

        response = client.get(
            f"{API_PREFIX}/collect/history?source_type=writing&status=failed&period=month"
        )

        assert response.status_code == 200
        items = response.json()["items"]
        found = next((item for item in items if item["id"] == run.id), None)
        assert found is not None
        assert found["error_message"] == run.error_message

    def test_collect_history_writing_failure_returns_stop_reason(self, client, test_db):
        """TC-Right: writing 실패 row는 stop_reason을 그대로 유지한다."""
        _, run = self._seed_failed_writing_run(test_db)

        response = client.get(
            f"{API_PREFIX}/collect/history?source_type=writing&status=failed&period=month"
        )

        assert response.status_code == 200
        items = response.json()["items"]
        found = next((item for item in items if item["id"] == run.id), None)
        assert found is not None
        assert found["stop_reason"] == "source_shortage"


# ============================================================
# Delete 테스트
# ============================================================

class TestDeleteSchedule:
    """스케줄 삭제 테스트"""

    def test_delete_schedule_without_runs(self, client, sample_service_account):
        """실행 이력 없는 스케줄 삭제"""
        # 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
        })
        schedule_id = create_resp.json()["id"]

        # 삭제 (이력 없으므로 delete_runs=false도 성공)
        response = client.delete(f"{API_PREFIX}/collect/schedules/{schedule_id}?delete_runs=false")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_runs"] == 0

        # 삭제 확인
        list_resp = client.get(f"{API_PREFIX}/collect/schedules")
        assert len(list_resp.json()) == 0

    def test_delete_schedule_with_runs(self, client):
        """실행 이력 있는 스케줄 삭제 (delete_runs=true)"""
        # 글쓰기 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
        })
        schedule_id = create_resp.json()["id"]

        # 즉시 실행으로 이력 생성
        client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        # 삭제 (이력 포함)
        response = client.delete(f"{API_PREFIX}/collect/schedules/{schedule_id}?delete_runs=true")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted_runs"] >= 1

    def test_delete_schedule_with_runs_requires_flag(self, client):
        """실행 이력 있는 스케줄 삭제 시 delete_runs 필요"""
        # 글쓰기 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
        })
        schedule_id = create_resp.json()["id"]

        # 즉시 실행으로 이력 생성
        client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        # delete_runs=false로 삭제 시도 (이력 있으므로 실패해야 함)
        response = client.delete(f"{API_PREFIX}/collect/schedules/{schedule_id}?delete_runs=false")

        assert response.status_code == 400
        assert "실행 이력이 있습니다" in response.json()["detail"]

    def test_delete_nonexistent_schedule(self, client):
        """존재하지 않는 스케줄 삭제"""
        response = client.delete(f"{API_PREFIX}/collect/schedules/99999?delete_runs=true")

        assert response.status_code == 404


# ============================================================
# target_config (LLM provider/model) 저장 테스트
# ============================================================

class TestUpdateScheduleTargetConfig:
    """PUT /collect/schedules/{id} - target_config 저장 검증"""

    def _create_writing_schedule(self, client):
        """writing_task 스케줄 생성 헬퍼"""
        resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
            "schedule_type": "time_window",
            "schedule_value": {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "12:00"}]
            }
        })
        assert resp.status_code == 200
        return resp.json()["id"]

    def test_update_schedule_target_config_right(self, client):
        """TC-Right: writing_task 스케줄에 llm_provider=gemini 저장"""
        schedule_id = self._create_writing_schedule(client)

        response = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini", "llm_model": ""}
        })

        assert response.status_code == 200
        data = response.json()
        assert data.get("target_config", {}).get("llm_provider") == "gemini"

    def test_update_schedule_target_config_merge(self, client, sample_service_account):
        """TC-Merge: 기존 service_account_id가 있는 스케줄에 llm_provider 추가 시 기존 값 보존"""
        # instagram_feed 스케줄 생성 (service_account_id 포함)
        resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
            "schedule_type": "time_window",
            "schedule_value": {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "12:00"}]
            }
        })
        schedule_id = resp.json()["id"]

        # llm_provider 추가
        response = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini", "llm_model": "gemini-2.0-flash"}
        })

        assert response.status_code == 200
        data = response.json()
        tc = data.get("target_config", {})
        assert tc.get("llm_provider") == "gemini"
        # 기존 service_account_id 보존 확인
        assert tc.get("service_account_id") == sample_service_account.id

    def test_update_schedule_target_config_null(self, client):
        """TC-Boundary: target_config=null PUT → 기존 target_config 변경 없음"""
        schedule_id = self._create_writing_schedule(client)

        # 먼저 llm_provider 설정
        client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini"}
        })

        # target_config=None (생략) PUT
        response = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "display_name": "변경된이름"
        })

        assert response.status_code == 200
        data = response.json()
        # target_config 변경 없음
        tc = data.get("target_config", {})
        assert tc.get("llm_provider") == "gemini"

    def test_get_schedules_returns_target_config(self, client):
        """TC-GET: writing_task 스케줄에 llm_provider=gemini PUT 후 GET 목록에서 target_config 확인.

        프론트엔드 폼 초기값 설정에 필요한 데이터가 목록 응답에 포함되는지 검증.
        """
        schedule_id = self._create_writing_schedule(client)

        # llm_provider=gemini 설정
        client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini", "llm_model": ""}
        })

        # GET 목록에서 확인
        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        schedules = response.json()
        assert len(schedules) >= 1

        found = next((s for s in schedules if s["id"] == schedule_id), None)
        assert found is not None, "생성한 스케줄이 목록에 없음"
        tc = found.get("target_config") or {}
        assert tc.get("llm_provider") == "gemini", (
            f"GET /collect/schedules 응답에 llm_provider=gemini 없음: {tc}"
        )

    def test_get_schedules_returns_audit_fields(self, client):
        """TC-Audit: 목록 응답에 resolved/provider/source 필드가 포함된다."""
        schedule_id = self._create_writing_schedule(client)

        client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini", "llm_model": "gemini-2.0-flash"}
        })

        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        schedules = response.json()
        found = next((s for s in schedules if s["id"] == schedule_id), None)
        assert found is not None
        assert found["resolved_provider"] == "gemini"
        assert found["resolved_model"] == "gemini-2.0-flash"
        assert found["resolution_source"] == "schedule_pin"
        assert found["legacy_placeholder_candidate"] is False

    def test_get_schedule_detail_returns_legacy_placeholder_audit(self, client):
        """TC-Audit: legacy placeholder는 detail 응답에서 candidate로 노출된다."""
        schedule_id = self._create_writing_schedule(client)

        client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "claude", "llm_model": ""}
        })

        response = client.get(f"{API_PREFIX}/collect/schedules/{schedule_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["legacy_placeholder_candidate"] is True
        assert data["resolution_source"] == "legacy_placeholder"
        assert data["resolved_provider"]
        assert data["resolved_model"] is not None

    def test_repair_legacy_placeholder_preview_and_apply(self, client):
        """TC-Repair: preview는 읽기 전용, apply는 candidate만 제거한다."""
        schedule_id = self._create_writing_schedule(client)
        client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "claude", "llm_model": ""}
        })

        preview = client.post(f"{API_PREFIX}/collect/schedules/repair-legacy-placeholder")
        assert preview.status_code == 200
        preview_data = preview.json()
        assert preview_data["candidate_count"] == 1
        assert preview_data["repaired_count"] == 0
        assert len(preview_data["items"]) == 1
        assert preview_data["items"][0]["before"]["llm_provider"] == "claude"
        assert "llm_provider" not in preview_data["items"][0]["after"]

        apply_resp = client.post(f"{API_PREFIX}/collect/schedules/repair-legacy-placeholder/apply")
        assert apply_resp.status_code == 200
        apply_data = apply_resp.json()
        assert apply_data["candidate_count"] == 1
        assert apply_data["repaired_count"] == 1

        detail = client.get(f"{API_PREFIX}/collect/schedules/{schedule_id}")
        assert detail.status_code == 200
        detail_data = detail.json()
        assert detail_data["legacy_placeholder_candidate"] is False
        assert detail_data["resolution_source"] in {"inherit", "caller_default"}

    def test_update_schedule_target_config_remove_llm_keys(self, client):
        """TC-Remove: llm_provider/model null PATCH → 키 제거 확인."""
        schedule_id = self._create_writing_schedule(client)

        response = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": "gemini", "llm_model": "gemini-3-flash"}
        })
        assert response.status_code == 200

        response = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": None, "llm_model": None}
        })

        assert response.status_code == 200
        data = response.json()
        tc = data.get("target_config") or {}
        assert "llm_provider" not in tc
        assert "llm_model" not in tc

    def test_pytest_schedule_target_config_roundtrip(self, client):
        """TC-RoundTrip: pytest_run create/update에서 llm_provider/model 왕복."""
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "pytest_run",
            "target_config": {
                "test_path": "tests/test_sample.py",
                "extra_args": ["-q"],
                "auto_fix_plan": True,
                "llm_provider": "claude",
                "llm_model": "claude-sonnet-4-6",
            },
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })
        assert create_resp.status_code == 200
        schedule_id = create_resp.json()["id"]

        detail_resp = client.get(f"{API_PREFIX}/collect/schedules/{schedule_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        tc = detail.get("target_config") or {}
        assert tc.get("llm_provider") == "claude"
        assert tc.get("llm_model") == "claude-sonnet-4-6"

        update_resp = client.put(f"{API_PREFIX}/collect/schedules/{schedule_id}", json={
            "target_config": {"llm_provider": None, "llm_model": None}
        })
        assert update_resp.status_code == 200
        updated = update_resp.json()
        updated_tc = updated.get("target_config") or {}
        assert "llm_provider" not in updated_tc
        assert "llm_model" not in updated_tc


class TestScheduleTimeWindowContract:
    """time_windows start/end range contract."""

    def test_create_exact_time_window_rejected(self, client, sample_service_account):
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "instagram_feed",
            "target_config": {"service_account_id": sample_service_account.id},
            "schedule_type": "time_window",
            "schedule_value": {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "09:00"}],
            },
        })

        assert response.status_code == 422
        assert "start" in response.json()["detail"]

    def test_exact_legacy_detail_requires_repair_and_update_path_blocks_resave(
        self,
        client,
        test_db,
        sample_service_account,
    ):
        schedule = TaskSchedule(
            name="instagram_feed_account_legacy_exact",
            target_type=TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
            schedule_value='{"daily_runs": 1, "time_windows": [{"start": "09:00", "end": "09:00"}]}',
        )
        schedule.set_target_config({"service_account_id": sample_service_account.id})
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)

        detail = client.get(f"{API_PREFIX}/collect/schedules/{schedule.id}")
        assert detail.status_code == 200
        detail_data = detail.json()
        assert detail_data["requires_time_window_repair"] is True
        assert detail_data["candidate_count_next_24h"] == 0
        assert detail_data["schedule_health"] == "error"
        assert detail_data["schedule_health_reason"] == "exact_time_window_zero_candidates"

        blocked = client.put(f"{API_PREFIX}/collect/schedules/{schedule.id}", json={
            "schedule_value": {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "09:00"}],
            }
        })
        assert blocked.status_code == 422

        repaired = client.put(f"{API_PREFIX}/collect/schedules/{schedule.id}", json={
            "schedule_value": {
                "daily_runs": 1,
                "time_windows": [{"start": "09:00", "end": "12:00"}],
            }
        })
        assert repaired.status_code == 200
        repaired_data = repaired.json()
        assert repaired_data["requires_time_window_repair"] is False
        assert repaired_data["schedule_health"] == "ok"
        assert repaired_data["candidate_count_next_24h"] == 1

    def test_google_exact_legacy_detail_reports_zero_candidate_health(
        self,
        client,
        test_db,
        sample_saved_search,
    ):
        schedule = TaskSchedule(
            name="google_search_legacy_exact",
            target_type=TaskSchedule.TARGET_TYPE_GOOGLE_SEARCH,
            schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
            enabled=True,
            schedule_value='{"daily_runs": 1, "time_windows": [{"start": "09:00", "end": "09:00"}]}',
        )
        schedule.set_target_config({"saved_search_id": sample_saved_search.id})
        test_db.add(schedule)
        test_db.commit()
        test_db.refresh(schedule)

        detail = client.get(f"{API_PREFIX}/collect/schedules/{schedule.id}")

        assert detail.status_code == 200
        detail_data = detail.json()
        assert detail_data["requires_time_window_repair"] is True
        assert detail_data["candidate_count_next_24h"] == 0
        assert detail_data["schedule_health"] == "error"
        assert detail_data["schedule_health_reason"] == "exact_time_window_zero_candidates"


# ============================================================
# T5: feat-scheduler-daily-disable — collect CRUD 경계 검증
# ============================================================

def _seed_internal_schedule(test_db, target_type: str) -> int:
    """internal schedule 1건을 DB에 직접 삽입하고 id 반환."""
    ts = TaskSchedule(
        name=f"internal_{target_type}_test",
        display_name="internal test schedule",
        target_type=target_type,
        target_config="{}",
        schedule_type="cron",
        schedule_value='{"time": "01:00"}',
        enabled=True,
    )
    test_db.add(ts)
    test_db.commit()
    test_db.refresh(ts)
    return ts.id


def _seed_run_supported_schedule(test_db, target_type: str, display_name: str) -> int:
    """즉시 실행 지원 타입 스케줄 1건을 DB에 직접 삽입하고 id 반환."""
    ts = TaskSchedule(
        name=f"manual_{target_type}_test",
        display_name=display_name,
        target_type=target_type,
        schedule_type="time_window",
        schedule_value='{"daily_runs": 1, "time_windows": []}',
        enabled=True,
    )
    test_db.add(ts)
    test_db.commit()
    test_db.refresh(ts)
    return ts.id


class TestCollectScheduleHidesInternalSchedules:
    """collect /schedules 목록에서 internal schedule이 숨겨진다."""

    def test_list_excludes_archive_rotation_right(self, client, test_db):
        """[Right] GET /api/v1/collect/schedules 응답에 archive_rotation 타입이 없다."""
        _seed_internal_schedule(test_db, TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION)
        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        types = [s.get("target_type") for s in response.json()]
        assert TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION not in types, \
            f"archive_rotation이 collect 목록에 노출됨: {types}"

    def test_list_excludes_schedule_date_expire_right(self, client, test_db):
        """[Right] GET /api/v1/collect/schedules 응답에 schedule_date_expire 타입이 없다."""
        _seed_internal_schedule(test_db, TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE)
        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        types = [s.get("target_type") for s in response.json()]
        assert TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE not in types, \
            f"schedule_date_expire가 collect 목록에 노출됨: {types}"

    def test_list_excludes_nightly_repo_sync_right(self, client, test_db):
        """[Right] GET /api/v1/collect/schedules 응답에 nightly_repo_sync 타입이 없다."""
        _seed_internal_schedule(test_db, TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC)
        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        types = [s.get("target_type") for s in response.json()]
        assert TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC not in types, \
            f"nightly_repo_sync가 collect 목록에 노출됨: {types}"

    @pytest.mark.parametrize(
        "target_type",
        [
            TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
            TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
            TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        ],
    )
    def test_detail_internal_schedule_returns_404_right(self, client, test_db, target_type):
        """[Right] GET /api/v1/collect/schedules/{internal_id} → 404."""
        internal_id = _seed_internal_schedule(test_db, target_type)
        response = client.get(f"{API_PREFIX}/collect/schedules/{internal_id}")
        assert response.status_code == 404, \
            f"internal schedule 상세 조회가 404가 아님: {response.status_code}"

    @pytest.mark.parametrize(
        "target_type",
        [
            TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
            TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
            TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        ],
    )
    def test_update_internal_schedule_returns_404_right(self, client, test_db, target_type):
        """[Right] PUT /api/v1/collect/schedules/{internal_id} → 404."""
        internal_id = _seed_internal_schedule(test_db, target_type)
        response = client.put(f"{API_PREFIX}/collect/schedules/{internal_id}", json={
            "target_config": {}
        })
        assert response.status_code == 404, \
            f"internal schedule 수정이 404가 아님: {response.status_code}"

    @pytest.mark.parametrize(
        "target_type",
        [
            TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
            TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
            TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        ],
    )
    def test_toggle_internal_schedule_returns_404_right(self, client, test_db, target_type):
        """[Right] POST /api/v1/collect/schedules/{internal_id}/toggle → 404."""
        internal_id = _seed_internal_schedule(test_db, target_type)
        response = client.post(f"{API_PREFIX}/collect/schedules/{internal_id}/toggle?enabled=true")
        assert response.status_code == 404, \
            f"internal schedule toggle이 404가 아님: {response.status_code}"

    @pytest.mark.parametrize(
        "target_type",
        [
            TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
            TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
            TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        ],
    )
    def test_delete_internal_schedule_returns_404_right(self, client, test_db, target_type):
        """[Right] DELETE /api/v1/collect/schedules/{internal_id} → 404."""
        internal_id = _seed_internal_schedule(test_db, target_type)
        response = client.delete(f"{API_PREFIX}/collect/schedules/{internal_id}")
        assert response.status_code == 404, \
            f"internal schedule 삭제가 404가 아님: {response.status_code}"

    @pytest.mark.parametrize(
        "target_type",
        [
            TaskSchedule.TARGET_TYPE_ARCHIVE_ROTATION,
            TaskSchedule.TARGET_TYPE_SCHEDULE_DATE_EXPIRE,
            TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC,
        ],
    )
    def test_create_internal_schedule_is_unsupported_right(self, client, target_type):
        """[Right] POST /api/v1/collect/schedules에 internal target_type → unsupported 오류."""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": target_type,
            "target_config": {},
            "schedule_type": "cron",
            "schedule_value": {"time": "01:00"},
        })
        assert response.status_code in (400, 422), \
            f"{target_type} create가 거부되지 않음: {response.status_code}"

    def test_run_nightly_repo_sync_internal_schedule_returns_404_right(self, client, test_db):
        """[Right] POST /api/v1/collect/schedules/{id}/run → 404 for nightly_repo_sync."""
        internal_id = _seed_internal_schedule(test_db, TaskSchedule.TARGET_TYPE_NIGHTLY_REPO_SYNC)
        response = client.post(f"{API_PREFIX}/collect/schedules/{internal_id}/run")
        assert response.status_code == 404, \
            f"nightly_repo_sync manual run이 404가 아님: {response.status_code}"


# ============================================================
# auto_dev_runner 스케줄 타입 테스트
# ============================================================

class TestAutoDevRunnerSchedule:
    """auto_dev_runner 스케줄 create/list/toggle/run 시나리오"""

    def test_create_auto_dev_runner_right(self, client):
        """[Right] auto_dev_runner 스케줄 생성 성공"""
        response = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "auto_dev_runner",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["target_type"] == "auto_dev_runner"

    def test_list_includes_auto_dev_runner_right(self, client):
        """[Right] 생성된 auto_dev_runner 스케줄이 목록에 포함됨"""
        client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "auto_dev_runner",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })
        response = client.get(f"{API_PREFIX}/collect/schedules")
        assert response.status_code == 200
        types = [s["target_type"] for s in response.json()]
        assert "auto_dev_runner" in types

    def test_toggle_auto_dev_runner_right(self, client):
        """[Right] auto_dev_runner 스케줄 비활성화 토글"""
        create = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "auto_dev_runner",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })
        sid = create.json()["id"]

        response = client.post(f"{API_PREFIX}/collect/schedules/{sid}/toggle?enabled=false")
        assert response.status_code == 200
        assert response.json()["enabled"] is False

    def test_run_auto_dev_runner_right(self, client):
        """[Right] auto_dev_runner 수동 실행 요청 성공"""
        create = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "auto_dev_runner",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        })
        sid = create.json()["id"]

        response = client.post(f"{API_PREFIX}/collect/schedules/{sid}/run")
        assert response.status_code == 200

    def test_create_duplicate_auto_dev_runner_right(self, client):
        """[Right] auto_dev_runner 중복 생성 시 400"""
        payload = {
            "target_type": "auto_dev_runner",
            "schedule_type": "cron",
            "schedule_value": {"time": "02:00"},
        }
        client.post(f"{API_PREFIX}/collect/schedules", json=payload)
        response = client.post(f"{API_PREFIX}/collect/schedules", json=payload)
        assert response.status_code == 400
