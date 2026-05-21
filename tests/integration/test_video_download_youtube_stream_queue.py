"""YouTube Live video download queue integration tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService
from app.worker import video_download_worker as worker_module
from app.worker.video_download_worker import VideoDownloadWorker


@pytest.fixture
def test_db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VideoDownload.__table__.create(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_youtube_stream_ffmpeg_failure_marks_request_failed(monkeypatch, test_db_engine, tmp_path):
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    queued_tasks = []

    with session_factory() as db:
        db.query(VideoDownload).delete(synchronize_session=False)
        db.commit()
        request = VideoDownloadService(db).create_request("https://www.youtube.com/live/PHEGRsZckhI")
        request_id = request.id

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)

    worker = VideoDownloadWorker(output_dir=str(tmp_path), max_concurrent=1)

    def fake_create_task(coro, task_name):
        queued_tasks.append((coro, task_name))

    async def fake_download_youtube_stream(request):
        return {
            "success": False,
            "error": "YouTube Live 녹화/병합 실패: ffmpeg exited with code 3199971767",
        }

    monkeypatch.setattr(worker, "_create_task", fake_create_task)
    monkeypatch.setattr(worker, "_download_youtube_stream", fake_download_youtube_stream)

    await worker._dispatch_pending_requests(limit=1)

    assert len(queued_tasks) == 1
    assert queued_tasks[0][1] == f"download_{request_id}"

    await queued_tasks[0][0]

    with session_factory() as db:
        failed = db.query(VideoDownload).filter(VideoDownload.id == request_id).first()
        assert failed is not None
        assert failed.download_type == VideoDownload.TYPE_YOUTUBE_STREAM
        assert failed.status == VideoDownload.STATUS_FAILED
        assert "ffmpeg exited with code 3199971767" in (failed.error_message or "")
        assert "다운로드된 파일을 찾을 수 없음" not in (failed.error_message or "")


@pytest.mark.asyncio
async def test_youtube_stream_failure_preserves_artifact_basenames(monkeypatch, test_db_engine, tmp_path):
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    queued_tasks = []

    with session_factory() as db:
        db.query(VideoDownload).delete(synchronize_session=False)
        db.commit()
        request = VideoDownloadService(db).create_request("https://www.youtube.com/live/PHEGRsZckhI")
        request_id = request.id

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)

    worker = VideoDownloadWorker(output_dir=str(tmp_path), max_concurrent=1)

    def fake_create_task(coro, task_name):
        queued_tasks.append((coro, task_name))

    async def fake_download_youtube_stream(request):
        return {
            "success": False,
            "error": (
                "YouTube Live 녹화/병합 실패: ffmpeg exited with code 3199971767 "
                "(artifacts=ts_20260521_120000.info.json, ts_20260521_120000.mp4.part)"
            ),
        }

    monkeypatch.setattr(worker, "_create_task", fake_create_task)
    monkeypatch.setattr(worker, "_download_youtube_stream", fake_download_youtube_stream)

    await worker._dispatch_pending_requests(limit=1)
    assert len(queued_tasks) == 1

    await queued_tasks[0][0]

    with session_factory() as db:
        failed = db.query(VideoDownload).filter(VideoDownload.id == request_id).first()
        assert failed is not None
        assert failed.status == VideoDownload.STATUS_FAILED
        assert "ts_20260521_120000.info.json" in (failed.error_message or "")
        assert "ts_20260521_120000.mp4.part" in (failed.error_message or "")
