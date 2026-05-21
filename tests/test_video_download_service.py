"""Video download service tests."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService


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


def _clear_video_downloads(test_db_session):
    test_db_session.query(VideoDownload).delete(synchronize_session=False)
    test_db_session.commit()


def test_detect_download_type_instagram_reel(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    detected = service.detect_download_type("https://www.instagram.com/reel/C8abc123xyz/")

    assert detected == VideoDownload.TYPE_INSTAGRAM


def test_detect_download_type_instagram_short_domain(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    detected = service.detect_download_type("https://instagr.am/reel/C8abc123xyz/")

    assert detected == VideoDownload.TYPE_INSTAGRAM


def test_detect_download_type_instagram_post_permalink(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    detected = service.detect_download_type("https://www.instagram.com/p/C8abc123xyz/")

    assert detected == VideoDownload.TYPE_INSTAGRAM


def test_create_request_auto_detects_instagram(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    request = service.create_request("https://www.instagram.com/reel/C8abc123xyz/")

    assert request.download_type == VideoDownload.TYPE_INSTAGRAM
    assert request.status == VideoDownload.STATUS_PENDING


def test_create_batch_requests_only_apply_embedding_url_to_vimeo(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    created, skipped = service.create_batch_requests(
        urls=[
            "https://vimeo.com/123456789",
            "https://www.instagram.com/reel/C8abc123xyz/",
        ],
        embedding_url="https://example.com/embed-page",
        output_prefix="batch_",
    )

    assert skipped == 0
    assert len(created) == 2
    assert created[0].download_type == VideoDownload.TYPE_VIMEO
    assert created[0].embedding_url == "https://example.com/embed-page"
    assert created[1].download_type == VideoDownload.TYPE_INSTAGRAM
    assert created[1].embedding_url is None
    assert created[1].output_filename == "batch_02"


def test_detect_download_type_keeps_default_fallback_for_unknown_url(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)

    detected = service.detect_download_type("https://example.com/video.mp4")

    assert detected == VideoDownload.TYPE_YOUTUBE


def test_retry_request_resets_previous_error_and_output_metadata(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)
    request = VideoDownload(
        url="https://www.youtube.com/live/example",
        download_type=VideoDownload.TYPE_YOUTUBE_STREAM,
        status=VideoDownload.STATUS_FAILED,
        quality="best",
        progress=67,
        error_message="YouTube Live 녹화/병합 실패: ffmpeg exited with code 3199971767",
        output_path="D:\\Videos\\contents\\download\\old.mp4",
        file_size=1234,
        title="old title",
        picked_at=datetime.now(),
        processed_at=datetime.now(),
        worker_id="worker-1",
    )
    test_db_session.add(request)
    test_db_session.commit()

    retried = service.retry_request(request.id)

    assert retried is not None
    assert retried.status == VideoDownload.STATUS_PENDING
    assert retried.progress == 0
    assert retried.error_message is None
    assert retried.output_path is None
    assert retried.file_size is None
    assert retried.title is None
    assert retried.picked_at is None
    assert retried.processed_at is None
    assert retried.worker_id is None


def test_cleanup_stale_processing_preserves_existing_youtube_live_error(test_db_session):
    _clear_video_downloads(test_db_session)
    service = VideoDownloadService(test_db_session)
    specific_error = "YouTube Live 녹화/병합 실패: ffmpeg exited with code 3199971767"
    request = VideoDownload(
        url="https://www.youtube.com/live/example",
        download_type=VideoDownload.TYPE_YOUTUBE_STREAM,
        status=VideoDownload.STATUS_PROCESSING,
        quality="best",
        picked_at=datetime.now() - timedelta(minutes=180),
        error_message=specific_error,
    )
    test_db_session.add(request)
    test_db_session.commit()

    cleaned = service.cleanup_stale_processing(timeout_minutes=120)
    test_db_session.refresh(request)

    assert cleaned == 1
    assert request.status == VideoDownload.STATUS_FAILED
    assert request.error_message == specific_error
