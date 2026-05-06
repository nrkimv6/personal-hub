"""Video download API contract tests."""

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import VideoDownload


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        yield test_db_session

    test_db_session.query(VideoDownload).delete(synchronize_session=False)
    test_db_session.commit()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_download_request_auto_detects_instagram(client):
    response = client.post(
        "/api/v1/video-downloads",
        json={"url": "https://www.instagram.com/reel/C8abc123xyz/"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["download_type"] == "instagram"
    assert data["status"] == "pending"


def test_list_download_requests_uses_page_size_contract(client, test_db_session):
    rows = [
        VideoDownload(
            url=f"https://www.instagram.com/reel/C8abc123xy{i}/",
            download_type=VideoDownload.TYPE_INSTAGRAM,
            status=VideoDownload.STATUS_PENDING,
            quality="best",
        )
        for i in range(3)
    ]
    test_db_session.add_all(rows)
    test_db_session.commit()

    response = client.get("/api/v1/video-downloads?download_type=instagram&page=1&page_size=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total_pages"] == 2
    assert all(item["download_type"] == "instagram" for item in data["items"])


def test_batch_download_request_accepts_instagram_urls(client):
    response = client.post(
        "/api/v1/video-downloads/batch",
        json={
            "urls": [
                "https://www.instagram.com/reel/C8abc123xyz/",
                "https://www.youtube.com/watch?v=abcdefghijk",
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["created_count"] == 2
    assert data["skipped_count"] == 0
