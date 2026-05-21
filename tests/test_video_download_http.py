"""Video download HTTP tests for merge-test."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import VideoDownload

pytestmark = pytest.mark.http


@pytest.fixture
def test_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VideoDownload.__table__.create(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


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


def test_create_instagram_reel_request_returns_pending(client):
    response = client.post(
        "/api/v1/video-downloads",
        json={"url": "https://www.instagram.com/reel/C8merge123xyz/"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["download_type"] == "instagram"
    assert body["status"] == "pending"


def test_list_and_stats_include_instagram_type(client, test_db_session):
    rows = [
        VideoDownload(
            url="https://www.instagram.com/reel/C8merge123xyz/",
            download_type=VideoDownload.TYPE_INSTAGRAM,
            status=VideoDownload.STATUS_COMPLETED,
            quality="best",
            progress=100,
        ),
        VideoDownload(
            url="https://www.instagram.com/reel/C8merge456xyz/",
            download_type=VideoDownload.TYPE_INSTAGRAM,
            status=VideoDownload.STATUS_FAILED,
            quality="best",
            error_message="Instagram 로그인 필요: 공개 Reel만 1차 지원합니다.",
        ),
    ]
    test_db_session.add_all(rows)
    test_db_session.commit()

    listed = client.get("/api/v1/video-downloads?download_type=instagram&page=1&page_size=10")
    assert listed.status_code == 200
    list_body = listed.json()
    assert list_body["total"] == 2
    assert list_body["page_size"] == 10
    assert all(item["download_type"] == "instagram" for item in list_body["items"])

    stats = client.get("/api/v1/video-downloads/stats")
    assert stats.status_code == 200
    stats_body = stats.json()
    assert stats_body["completed"] >= 1
    assert stats_body["failed"] >= 1


def test_batch_mixed_urls_accepts_instagram_with_existing_types(client):
    response = client.post(
        "/api/v1/video-downloads/batch",
        json={
            "urls": [
                "https://www.instagram.com/reel/C8merge123xyz/",
                "https://www.youtube.com/watch?v=abcdefghijk",
                "https://vimeo.com/123456789",
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["created_count"] == 3
    assert body["skipped_count"] == 0


def test_get_youtube_stream_failed_request_preserves_error_message(client, test_db_session):
    error_message = "YouTube Live 녹화/병합 실패: ffmpeg exited with code 3199971767"
    row = VideoDownload(
        url="https://www.youtube.com/live/PHEGRsZckhI",
        download_type=VideoDownload.TYPE_YOUTUBE_STREAM,
        status=VideoDownload.STATUS_FAILED,
        quality="best",
        error_message=error_message,
    )
    test_db_session.add(row)
    test_db_session.commit()

    response = client.get(f"/api/v1/video-downloads/{row.id}")

    assert response.status_code == 200
    assert response.json()["error_message"] == error_message


def test_list_youtube_stream_failed_request_preserves_error_message(client, test_db_session):
    error_message = "YouTube Live 접근 권한 또는 로그인 필요: Private video. Sign in."
    row = VideoDownload(
        url="https://www.youtube.com/live/PHEGRsZckhI",
        download_type=VideoDownload.TYPE_YOUTUBE_STREAM,
        status=VideoDownload.STATUS_FAILED,
        quality="best",
        error_message=error_message,
    )
    test_db_session.add(row)
    test_db_session.commit()

    response = client.get("/api/v1/video-downloads?download_type=youtube_stream&page=1&page_size=10")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["error_message"] == error_message
