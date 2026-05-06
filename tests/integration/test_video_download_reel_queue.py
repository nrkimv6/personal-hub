"""Video download queue integration tests."""

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import VideoDownload
from app.services.video_download_service import VideoDownloadService
from app.worker import video_download_worker as worker_module
from app.worker.video_download_worker import VideoDownloadWorker


@pytest.mark.asyncio
async def test_instagram_reel_request_flows_through_queue(monkeypatch, test_db_engine, tmp_path):
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    queued_tasks = []

    with session_factory() as db:
        db.query(VideoDownload).delete(synchronize_session=False)
        db.commit()
        request = VideoDownloadService(db).create_request("https://www.instagram.com/reel/C8abc123xyz/")
        request_id = request.id

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)

    worker = VideoDownloadWorker(output_dir=str(tmp_path), max_concurrent=1)

    def fake_create_task(coro, task_name):
        queued_tasks.append((coro, task_name))

    async def fake_download_instagram(request):
        return {
            "success": True,
            "output_path": str(tmp_path / "reel.mp4"),
            "file_size": 4096,
            "title": "Test reel",
        }

    monkeypatch.setattr(worker, "_create_task", fake_create_task)
    monkeypatch.setattr(worker, "_download_instagram", fake_download_instagram)

    await worker._dispatch_pending_requests(limit=1)

    assert len(queued_tasks) == 1
    assert queued_tasks[0][1] == f"download_{request_id}"

    with session_factory() as db:
        picked = db.query(VideoDownload).filter(VideoDownload.id == request_id).first()
        assert picked is not None
        assert picked.download_type == VideoDownload.TYPE_INSTAGRAM
        assert picked.status == VideoDownload.STATUS_PICKED
        assert picked.worker_id == worker.name

    await queued_tasks[0][0]

    with session_factory() as db:
        completed = db.query(VideoDownload).filter(VideoDownload.id == request_id).first()
        assert completed is not None
        assert completed.status == VideoDownload.STATUS_COMPLETED
        assert completed.output_path == str(tmp_path / "reel.mp4")
        assert completed.file_size == 4096
        assert completed.title == "Test reel"


@pytest.mark.asyncio
async def test_instagram_reel_login_required_marks_request_failed(monkeypatch, test_db_engine, tmp_path):
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    queued_tasks = []

    with session_factory() as db:
        db.query(VideoDownload).delete(synchronize_session=False)
        db.commit()
        request = VideoDownloadService(db).create_request("https://www.instagram.com/reel/C8abc999xyz/")
        request_id = request.id

    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)

    worker = VideoDownloadWorker(output_dir=str(tmp_path), max_concurrent=1)

    def fake_create_task(coro, task_name):
        queued_tasks.append((coro, task_name))

    async def fake_download_instagram(request):
        return {"success": False, "error": "Instagram 로그인 필요: 공개 Reel만 1차 지원합니다."}

    monkeypatch.setattr(worker, "_create_task", fake_create_task)
    monkeypatch.setattr(worker, "_download_instagram", fake_download_instagram)

    await worker._dispatch_pending_requests(limit=1)

    assert len(queued_tasks) == 1
    await queued_tasks[0][0]

    with session_factory() as db:
        failed = db.query(VideoDownload).filter(VideoDownload.id == request_id).first()
        assert failed is not None
        assert failed.status == VideoDownload.STATUS_FAILED
        assert "로그인 필요" in (failed.error_message or "")
