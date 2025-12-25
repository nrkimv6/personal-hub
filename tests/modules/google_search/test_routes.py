"""
Google 검색 API 라우트 테스트

RIGHT-BICEP 패턴:
- Right: 올바른 결과 반환
- Boundary: 경계 조건 테스트
- Inverse: 역관계 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트 (필요시)
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.google_search import (
    GoogleSavedSearch,
    GoogleSearchHistory,
    GoogleSearchResult,
)


@pytest.fixture
def client(test_db_session):
    """테스트용 FastAPI 클라이언트"""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample_saved_search(test_db_session):
    """테스트용 저장된 검색"""
    saved = GoogleSavedSearch(
        name="테스트 검색",
        query="python tutorial",
        date_filter="1w",
        max_pages=2,
        is_favorite=True,
    )
    test_db_session.add(saved)
    test_db_session.commit()
    test_db_session.refresh(saved)
    return saved


@pytest.fixture
def sample_history_with_results(test_db_session):
    """테스트용 검색 히스토리 및 결과"""
    import uuid
    history = GoogleSearchHistory(
        search_id=f"test-history-{uuid.uuid4().hex[:8]}",
        query="sample query",
        date_filter="24h",
        status="completed",
        total_results=3,
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )
    test_db_session.add(history)
    test_db_session.commit()

    for i in range(3):
        result = GoogleSearchResult(
            search_id=history.search_id,
            query="sample query",
            rank=i + 1,
            title=f"Result Title {i + 1}",
            url=f"https://example.com/result/{i}",
            display_url=f"example.com › result › {i}",
            snippet=f"This is snippet for result {i + 1}",
            page_number=1,
        )
        test_db_session.add(result)

    test_db_session.commit()
    return history


class TestSavedSearchListAPI:
    """GET /api/google/saved 테스트"""

    def test_list_saved_searches_empty(self, client, test_db_session):
        """Right: 빈 목록 조회"""
        # 테스트 격리를 위해 먼저 정리
        test_db_session.query(GoogleSavedSearch).delete()
        test_db_session.commit()

        response = client.get("/api/google/saved")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_saved_searches_with_data(self, client, sample_saved_search):
        """Right: 저장된 검색 목록 조회"""
        response = client.get("/api/google/saved")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["name"] == "테스트 검색"

    def test_list_saved_searches_favorite_only(self, client, sample_saved_search, test_db_session):
        """Boundary: 즐겨찾기만 필터링"""
        # 즐겨찾기가 아닌 검색 추가
        non_fav = GoogleSavedSearch(
            name="Non Favorite",
            query="non favorite query",
            is_favorite=False,
        )
        test_db_session.add(non_fav)
        test_db_session.commit()

        response = client.get("/api/google/saved?favorite_only=true")
        assert response.status_code == 200
        data = response.json()
        for item in data:
            assert item["is_favorite"] is True


class TestSavedSearchCreateAPI:
    """POST /api/google/saved 테스트"""

    def test_create_saved_search_right(self, client):
        """Right: 저장된 검색 생성"""
        response = client.post("/api/google/saved", json={
            "name": "새 검색",
            "query": "fastapi tutorial",
            "date_filter": "1m",
            "max_pages": 3,
            "is_favorite": False,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "새 검색"
        assert data["query"] == "fastapi tutorial"
        assert data["date_filter"] == "1m"
        assert data["max_pages"] == 3
        assert data["id"] is not None

    def test_create_saved_search_minimal(self, client):
        """Boundary: 최소 필드만으로 생성"""
        response = client.post("/api/google/saved", json={
            "name": "최소 검색",
            "query": "minimal",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "최소 검색"
        assert data["max_pages"] == 1
        assert data["is_favorite"] is False


class TestSavedSearchDetailAPI:
    """GET /api/google/saved/{id} 테스트"""

    def test_get_saved_search_right(self, client, sample_saved_search):
        """Right: 저장된 검색 상세 조회"""
        response = client.get(f"/api/google/saved/{sample_saved_search.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_saved_search.id
        assert data["name"] == "테스트 검색"

    def test_get_saved_search_not_found(self, client):
        """Error: 존재하지 않는 ID"""
        response = client.get("/api/google/saved/99999")
        assert response.status_code == 404


class TestSavedSearchUpdateAPI:
    """PUT /api/google/saved/{id} 테스트"""

    def test_update_saved_search_right(self, client, sample_saved_search):
        """Right: 저장된 검색 수정"""
        response = client.put(f"/api/google/saved/{sample_saved_search.id}", json={
            "name": "수정된 검색",
            "max_pages": 5,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "수정된 검색"
        assert data["max_pages"] == 5
        # 기존 값은 유지
        assert data["query"] == "python tutorial"

    def test_update_saved_search_not_found(self, client):
        """Error: 존재하지 않는 ID 수정"""
        response = client.put("/api/google/saved/99999", json={
            "name": "Not Found",
        })
        assert response.status_code == 404


class TestSavedSearchDeleteAPI:
    """DELETE /api/google/saved/{id} 테스트"""

    def test_delete_saved_search_right(self, client, sample_saved_search):
        """Right: 저장된 검색 삭제"""
        response = client.delete(f"/api/google/saved/{sample_saved_search.id}")
        assert response.status_code == 200

        # 삭제 확인
        response = client.get(f"/api/google/saved/{sample_saved_search.id}")
        assert response.status_code == 404

    def test_delete_saved_search_not_found(self, client):
        """Error: 존재하지 않는 ID 삭제"""
        response = client.delete("/api/google/saved/99999")
        assert response.status_code == 404


class TestToggleFavoriteAPI:
    """POST /api/google/saved/{id}/toggle-favorite 테스트"""

    def test_toggle_favorite_on(self, client, test_db_session):
        """Right: 즐겨찾기 활성화"""
        saved = GoogleSavedSearch(
            name="Toggle Test",
            query="toggle",
            is_favorite=False,
        )
        test_db_session.add(saved)
        test_db_session.commit()
        test_db_session.refresh(saved)

        response = client.post(f"/api/google/saved/{saved.id}/toggle-favorite")
        assert response.status_code == 200
        data = response.json()
        assert data["is_favorite"] is True

    def test_toggle_favorite_off(self, client, sample_saved_search):
        """Right: 즐겨찾기 비활성화"""
        # sample_saved_search는 is_favorite=True
        response = client.post(f"/api/google/saved/{sample_saved_search.id}/toggle-favorite")
        assert response.status_code == 200
        data = response.json()
        assert data["is_favorite"] is False

    def test_toggle_favorite_not_found(self, client):
        """Error: 존재하지 않는 ID"""
        response = client.post("/api/google/saved/99999/toggle-favorite")
        assert response.status_code == 404


class TestSearchResultsAPI:
    """GET /api/google/results/{search_id} 테스트"""

    def test_get_results_right(self, client, sample_history_with_results):
        """Right: 검색 결과 조회"""
        response = client.get(f"/api/google/results/{sample_history_with_results.search_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["search_id"] == sample_history_with_results.search_id
        assert data["query"] == "sample query"
        assert data["status"] == "completed"
        assert data["total_results"] == 3
        assert len(data["results"]) == 3

    def test_get_results_not_found(self, client):
        """Error: 존재하지 않는 search_id"""
        response = client.get("/api/google/results/non-existent-uuid")
        assert response.status_code == 404


class TestSearchHistoryAPI:
    """GET /api/google/history 테스트"""

    def test_get_history_empty(self, client, test_db_session):
        """Right: 빈 히스토리"""
        # 테스트 격리를 위해 먼저 정리
        test_db_session.query(GoogleSearchHistory).delete()
        test_db_session.commit()

        response = client.get("/api/google/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_history_with_data(self, client, sample_history_with_results):
        """Right: 히스토리 조회"""
        response = client.get("/api/google/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_get_history_limit(self, client, test_db_session):
        """Boundary: 히스토리 개수 제한"""
        # 5개 히스토리 생성
        for i in range(5):
            history = GoogleSearchHistory(
                search_id=f"limit-test-{i}",
                query=f"query {i}",
                status="completed",
            )
            test_db_session.add(history)
        test_db_session.commit()

        response = client.get("/api/google/history?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3


class TestDeleteHistoryAPI:
    """DELETE /api/google/history/{search_id} 테스트"""

    def test_delete_history_right(self, client, sample_history_with_results):
        """Right: 히스토리 삭제"""
        search_id = sample_history_with_results.search_id

        response = client.delete(f"/api/google/history/{search_id}")
        assert response.status_code == 200

        # 삭제 확인
        response = client.get(f"/api/google/results/{search_id}")
        assert response.status_code == 404

    def test_delete_history_not_found(self, client):
        """Error: 존재하지 않는 히스토리 삭제"""
        response = client.delete("/api/google/history/non-existent-uuid")
        assert response.status_code == 404
