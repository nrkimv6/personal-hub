"""Video download worker tests."""

from types import SimpleNamespace

import pytest

from app.models import VideoDownload
from app.worker.video_download_worker import VideoDownloadWorker


def test_format_yt_dlp_error_for_instagram_login_required():
    worker = VideoDownloadWorker(output_dir="D:\\Videos\\contents\\download")

    message = worker._format_yt_dlp_error(
        VideoDownload.TYPE_INSTAGRAM,
        "ERROR: Login required to access this content",
    )

    assert "로그인 필요" in message


def test_format_yt_dlp_error_for_instagram_rate_limit():
    worker = VideoDownloadWorker(output_dir="D:\\Videos\\contents\\download")

    message = worker._format_yt_dlp_error(
        VideoDownload.TYPE_INSTAGRAM,
        "HTTP Error 429: Too Many Requests",
    )

    assert "요청 제한" in message


@pytest.mark.asyncio
async def test_download_instagram_uses_instagram_filename_prefix(monkeypatch, tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))
    captured = {}

    async def fake_download_with_yt_dlp(request, output_filename, referer=None):
        captured["request"] = request
        captured["output_filename"] = output_filename
        captured["referer"] = referer
        return {"success": True, "output_path": f"{output_filename}.mp4"}

    monkeypatch.setattr(worker, "_download_with_yt_dlp", fake_download_with_yt_dlp)

    request = SimpleNamespace(
        url="https://www.instagram.com/reel/C8abc123xyz/",
        output_filename=None,
        download_type=VideoDownload.TYPE_INSTAGRAM,
    )

    result = await worker._download_instagram(request)

    assert result["success"] is True
    assert captured["request"] is request
    assert captured["referer"] is None
    assert captured["output_filename"].startswith(str(tmp_path))
    assert "instagram_" in captured["output_filename"]
