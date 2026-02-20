"""Notes API 테스트 공통 픽스처."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


@pytest.fixture(autouse=True)
def set_dev_mode(monkeypatch):
    """개발 모드 강제 설정."""
    monkeypatch.setenv("APP_MODE", "development")


@pytest.fixture
def client(test_db_session):
    """테스트 DB를 사용하는 API 클라이언트."""
    def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def unique_id():
    """테스트마다 고유한 식별자."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
def sample_note_data(unique_id):
    """기본 메모 데이터."""
    return {
        "title": f"테스트 메모 {unique_id}",
        "content": f"본문 내용 {unique_id}\n\n```python\nprint('hello')\n```",
        "remark": f"비고 {unique_id}",
    }


@pytest.fixture
def sample_note(client, sample_note_data):
    """API로 생성한 샘플 메모."""
    response = client.post("/api/notes", json=sample_note_data)
    assert response.status_code == 201, f"메모 생성 실패: {response.json()}"
    return response.json()


@pytest.fixture
def sample_tag_data(unique_id):
    """기본 태그 데이터."""
    return {"name": f"태그_{unique_id}", "color": "#3b82f6"}


@pytest.fixture
def sample_tag(client, sample_tag_data):
    """API로 생성한 샘플 태그."""
    response = client.post("/api/notes/tags", json=sample_tag_data)
    assert response.status_code == 201, f"태그 생성 실패: {response.json()}"
    return response.json()
