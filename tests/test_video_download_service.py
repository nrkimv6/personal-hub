"""Video download service tests."""

from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService


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
