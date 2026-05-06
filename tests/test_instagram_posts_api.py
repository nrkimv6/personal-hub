"""
Instagram Posts API 통합 테스트

검색 기능 및 필터 테스트 (2025-12-24 추가)
"""

from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.models.instagram_post import InstagramPost
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.modules.instagram.routes.instagram import router as instagram_router


@pytest.fixture
def client(test_db_session):
    """테스트용 FastAPI 클라이언트"""
    from app.main import app

    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def create_schedule_test_app() -> FastAPI:
    """Schedule API 계약만 검증하는 lightweight FastAPI app."""
    schedule_app = FastAPI()
    schedule_app.include_router(instagram_router)
    schedule_app.state.instagram_schedule_fixture_scope = "schedule-only"
    return schedule_app


@pytest.fixture
def schedule_app():
    app = create_schedule_test_app()
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def schedule_db_session():
    """Schedule API에 필요한 테이블만 가진 빠른 테스트 DB 세션."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TaskSchedule.__table__.create(bind=engine)
    TaskScheduleRun.__table__.create(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


@pytest.fixture
def schedule_client(schedule_app, schedule_db_session):
    """Instagram schedule API 전용 TestClient."""
    def override_get_db():
        try:
            yield schedule_db_session
        finally:
            pass

    schedule_app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(schedule_app)
    finally:
        schedule_app.dependency_overrides.clear()


@pytest.fixture
def sample_posts(test_db_session):
    """테스트용 게시물 생성 (격리된 데이터)"""
    import uuid

    # 유니크한 식별자 생성
    unique_id = uuid.uuid4().hex[:8]

    # 기존 테스트 데이터 정리 (해당 패턴만)
    test_db_session.query(InstagramPost).filter(
        InstagramPost.post_id.like("test_%")
    ).delete(synchronize_session=False)
    test_db_session.commit()

    posts = [
        InstagramPost(
            post_id=f"test_event_{unique_id}",
            account=f"test_event_acc_{unique_id}",
            url=f"https://instagram.com/p/test_event{unique_id}",
            caption=f"SEARCHTEST_{unique_id} 이벤트 진행중! #이벤트",
            collected_at=datetime.now(),
        ),
        InstagramPost(
            post_id=f"test_popup_{unique_id}",
            account=f"test_popup_acc_{unique_id}",
            url=f"https://instagram.com/p/test_popup{unique_id}",
            caption=f"SEARCHTEST_{unique_id} 팝업스토어 오픈!",
            collected_at=datetime.now(),
        ),
        InstagramPost(
            post_id=f"test_sale_{unique_id}",
            account=f"test_sale_acc_{unique_id}",
            url=f"https://instagram.com/p/test_sale{unique_id}",
            caption=f"SEARCHTEST_{unique_id} 50% 할인 이벤트!",
            collected_at=datetime.now(),
        ),
        InstagramPost(
            post_id=f"test_normal_{unique_id}",
            account=f"test_normal_acc_{unique_id}",
            url=f"https://instagram.com/p/test_normal{unique_id}",
            caption=f"SEARCHTEST_{unique_id} 일상 기록 #daily",
            collected_at=datetime.now(),
        ),
    ]

    for post in posts:
        test_db_session.add(post)
    test_db_session.commit()

    for post in posts:
        test_db_session.refresh(post)

    return posts, unique_id  # unique_id도 반환


@pytest.fixture
def clean_instagram_schedule(schedule_db_session):
    """Instagram 피드 스케줄 테스트 데이터 정리."""
    schedule_ids = [
        schedule_id
        for (schedule_id,) in schedule_db_session.query(TaskSchedule.id)
        .filter(TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED)
        .all()
    ]
    if schedule_ids:
        schedule_db_session.query(TaskScheduleRun).filter(
            TaskScheduleRun.schedule_id.in_(schedule_ids)
        ).delete(synchronize_session=False)
    schedule_db_session.query(TaskSchedule).filter(
        TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_INSTAGRAM_FEED
    ).delete(synchronize_session=False)
    schedule_db_session.commit()


@pytest.mark.http
class TestInstagramScheduleAPI:
    """GET/PUT /api/v1/instagram/schedule 계약 테스트."""

    def test_update_exact_slots_and_today_schedule_returns_all_slots(
        self,
        schedule_client,
        clean_instagram_schedule,
    ):
        """exact slot 10개 저장 후 today 응답도 10개 슬롯을 반환."""
        windows = [
            {"start": f"{hour:02d}:00", "end": f"{hour:02d}:00"}
            for hour in range(0, 20, 2)
        ]

        response = schedule_client.put(
            "/api/v1/instagram/schedule",
            json={
                "enabled": True,
                "daily_runs": 10,
                "time_windows": windows,
                "min_interval_hours": 0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["daily_runs"] == 10
        assert data["time_windows"] == windows

        today_response = schedule_client.get("/api/v1/instagram/schedule/today")

        assert today_response.status_code == 200
        today_items = today_response.json()
        assert [item["scheduled_time"] for item in today_items] == [
            window["start"] for window in windows
        ]
        assert len(today_items) == 10

    def test_update_exact_slots_rejects_min_interval_conflict(
        self,
        schedule_client,
        clean_instagram_schedule,
    ):
        """exact slot 간격보다 큰 min_interval_hours는 API 422로 거부."""
        response = schedule_client.put(
            "/api/v1/instagram/schedule",
            json={
                "enabled": True,
                "daily_runs": 2,
                "time_windows": [
                    {"start": "09:00", "end": "09:00"},
                    {"start": "10:00", "end": "10:00"},
                ],
                "min_interval_hours": 2,
            },
        )

        assert response.status_code == 422
        assert "min_interval_hours" in response.json()["detail"]

    def test_schedule_client_uses_lightweight_app_without_posts_fixture(
        self,
        schedule_client,
    ):
        """schedule API fixture는 posts sample fixture와 full app bootstrap을 공유하지 않는다."""
        assert schedule_client.app.state.instagram_schedule_fixture_scope == "schedule-only"

    def test_schedule_app_clears_dependency_overrides(
        self,
        schedule_app,
        schedule_db_session,
    ):
        """schedule app fixture의 DB override는 사용 후 제거 가능해야 한다."""
        def override_get_db():
            yield schedule_db_session

        schedule_app.dependency_overrides[get_db] = override_get_db

        assert get_db in schedule_app.dependency_overrides

        schedule_app.dependency_overrides.clear()

        assert schedule_app.dependency_overrides == {}


class TestInstagramPostsSearchAPI:
    """GET /api/v1/instagram/posts 검색 테스트"""

    def test_get_posts_without_search(self, client, sample_posts):
        """검색어 없이 조회"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts")
        assert response.status_code == 200
        data = response.json()
        assert "posts" in data
        assert "total" in data

    def test_get_posts_search_unique_keyword(self, client, sample_posts):
        """유니크 키워드로 검색 (격리된 테스트)"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id}")
        assert response.status_code == 200
        data = response.json()
        # 해당 unique_id를 포함하는 게시물만 조회
        assert data["total"] == 4

    def test_get_posts_search_event_keyword(self, client, sample_posts):
        """이벤트 키워드 검색"""
        posts, unique_id = sample_posts
        # unique_id와 이벤트를 함께 검색
        response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id} 이벤트")
        assert response.status_code == 200
        data = response.json()
        # "이벤트"가 포함된 게시물: event, sale
        assert data["total"] >= 1

    def test_get_posts_search_popup(self, client, sample_posts):
        """'팝업' 검색"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id} 팝업")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        if data["posts"]:
            assert "팝업" in data["posts"][0]["caption"]

    def test_get_posts_search_no_match(self, client, sample_posts):
        """매칭 없는 검색어"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts?search=존재하지않는유니크키워드xyz123")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["posts"]) == 0

    def test_get_posts_search_case_insensitive(self, client, sample_posts):
        """대소문자 구분 없이 검색"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=searchtest_{unique_id}")
        assert response.status_code == 200
        data = response.json()
        # SEARCHTEST 대소문자 무시
        assert data["total"] == 4

    def test_get_posts_search_with_hashtag(self, client, sample_posts):
        """해시태그 포함 검색"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=%23이벤트")
        assert response.status_code == 200
        # 에러 없이 응답

    def test_get_posts_search_special_chars(self, client, sample_posts):
        """특수문자 포함 검색"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts?search=50%")
        assert response.status_code == 200
        # 에러 없이 응답

    def test_get_posts_search_with_account_filter(self, client, sample_posts):
        """검색어 + 계정명 필터 조합"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id}&account=test_event_acc_{unique_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_get_posts_search_empty_string(self, client, sample_posts):
        """빈 검색어"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts?search=")
        assert response.status_code == 200
        # 빈 검색어는 필터링 없음

    def test_get_posts_search_with_pagination(self, client, sample_posts):
        """검색 + 페이지네이션"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id}&page=1&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["posts"]) == 2
        assert data["total"] == 4
        assert data["page"] == 1
        assert data["limit"] == 2


class TestInstagramPostsAPIFilters:
    """GET /api/v1/instagram/posts 필터 테스트"""

    def test_get_posts_filter_account(self, client, sample_posts):
        """계정명 필터"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?account=test_popup_acc_{unique_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_get_posts_filter_account_partial_match(self, client, sample_posts):
        """계정명 부분 일치"""
        posts, unique_id = sample_posts
        response = client.get(f"/api/v1/instagram/posts?account={unique_id}")
        assert response.status_code == 200
        data = response.json()
        # 해당 unique_id를 포함하는 계정 4개
        assert data["total"] == 4

    def test_get_posts_pagination(self, client, sample_posts):
        """페이지네이션"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts?page=1&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["posts"]) <= 2
        assert data["page"] == 1
        assert data["limit"] == 2

    def test_get_posts_sorting(self, client, sample_posts):
        """정렬"""
        posts, unique_id = sample_posts
        response = client.get("/api/v1/instagram/posts?sort_order=desc")
        assert response.status_code == 200
        # 에러 없이 응답


class TestInstagramPostsBatchAPI:
    """일괄 처리 API 테스트"""

    def test_batch_delete_posts(self, client, sample_posts):
        """일괄 삭제"""
        posts, unique_id = sample_posts
        post_ids = [posts[0].id, posts[1].id]

        response = client.post(
            "/api/v1/instagram/posts/batch/delete",
            json={"post_ids": post_ids}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted"] == 2
        assert data["total"] == 2

        # 삭제 확인
        check_response = client.get(f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id}")
        assert check_response.json()["total"] == 2  # 4 - 2 = 2

    def test_batch_delete_empty_list(self, client, sample_posts):
        """빈 리스트로 삭제 요청"""
        posts, unique_id = sample_posts

        response = client.post(
            "/api/v1/instagram/posts/batch/delete",
            json={"post_ids": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 0

    def test_batch_delete_nonexistent_ids(self, client, sample_posts):
        """존재하지 않는 ID로 삭제"""
        posts, unique_id = sample_posts

        response = client.post(
            "/api/v1/instagram/posts/batch/delete",
            json={"post_ids": [999999, 999998]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 0

    def test_batch_deactivate_posts(self, client, sample_posts):
        """일괄 비활성화"""
        posts, unique_id = sample_posts
        post_ids = [posts[0].id, posts[1].id]

        response = client.post(
            "/api/v1/instagram/posts/batch/deactivate",
            json={"post_ids": post_ids}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["updated"] == 2
        assert data["total"] == 2

        # 비활성화 확인 (is_active=true 필터로 조회)
        check_response = client.get(
            f"/api/v1/instagram/posts?search=SEARCHTEST_{unique_id}&is_active=true"
        )
        assert check_response.json()["total"] == 2  # 4 - 2 = 2

    def test_batch_deactivate_empty_list(self, client, sample_posts):
        """빈 리스트로 비활성화 요청"""
        posts, unique_id = sample_posts

        response = client.post(
            "/api/v1/instagram/posts/batch/deactivate",
            json={"post_ids": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 0

    def test_batch_deactivate_nonexistent_ids(self, client, sample_posts):
        """존재하지 않는 ID로 비활성화"""
        posts, unique_id = sample_posts

        response = client.post(
            "/api/v1/instagram/posts/batch/deactivate",
            json={"post_ids": [999999, 999998]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 0
