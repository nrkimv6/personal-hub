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
from unittest.mock import patch, MagicMock

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models.base import Base
from app.models import TaskSchedule, ServiceAccount, BrowserProfile
from app.models.google_search import GoogleSavedSearch


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

    # 테이블 생성
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def client(test_db):
    """테스트용 FastAPI 클라이언트"""
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
                    {"start": "09:00", "end": "09:00"},
                    {"start": "12:00", "end": "12:00"},
                    {"start": "18:00", "end": "18:00"},
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
        assert "saved_search_id" in response.json()["detail"]

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

    def test_run_writing_schedule(self, client):
        """글쓰기 스케줄 즉시 실행"""
        # 스케줄 생성
        create_resp = client.post(f"{API_PREFIX}/collect/schedules", json={
            "target_type": "writing_task",
        })
        schedule_id = create_resp.json()["id"]

        response = client.post(f"{API_PREFIX}/collect/schedules/{schedule_id}/run")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "run_id" in data

    def test_run_nonexistent_schedule(self, client):
        """존재하지 않는 스케줄 실행"""
        response = client.post(f"{API_PREFIX}/collect/schedules/99999/run")

        assert response.status_code == 404


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
