"""Video download worker tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import VideoDownload
from app.worker import video_download_worker as worker_module
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


def test_classify_youtube_stream_error_right_ffmpeg_exit_preserved(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))

    kind, message = worker._classify_youtube_stream_error(
        "ERROR: ffmpeg exited with code 3199971767",
        1,
    )

    assert kind == "youtube_live_ffmpeg_failed"
    assert "ffmpeg exited with code 3199971767" in message
    assert "다운로드된 파일을 찾을 수 없음" not in message


def test_classify_youtube_stream_error_boundary_empty_stderr_output_missing(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))

    kind, message = worker._classify_youtube_stream_error("", 0)

    assert kind == "youtube_live_output_missing"
    assert message == "다운로드된 파일을 찾을 수 없음"


def test_classify_youtube_stream_error_error_private_video_access_restricted(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))

    kind, message = worker._classify_youtube_stream_error(
        "ERROR: Private video. Sign in if you've been granted access to this video.",
        1,
    )

    assert kind == "youtube_live_access_restricted"
    assert "접근 권한 또는 로그인 필요" in message
    assert "Private video" in message


def test_build_youtube_stream_command_reference_uses_argv_not_shell(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))
    request = SimpleNamespace(
        url="https://m.youtube.com/live/PHEGRsZckhI?feature=share&x=1 2",
        quality="720",
    )
    output_base = str(tmp_path / "ts_20260521_120000")

    cmd = worker._build_youtube_stream_command(request, output_base)

    assert isinstance(cmd, list)
    assert cmd[0] == "yt-dlp"
    assert request.url in cmd
    assert "--print" in cmd
    assert "after_move:filepath" in cmd
    assert f"{output_base}.%(ext)s" in cmd
    assert not any(" " in arg and request.url in arg and arg != request.url for arg in cmd)


def test_quality_to_youtube_stream_format_range_known_values(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))

    assert worker._quality_to_youtube_stream_format("best") == "bv*+ba/best"
    assert worker._quality_to_youtube_stream_format("1080") == "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]"
    assert worker._quality_to_youtube_stream_format("720") == "bv*[height<=720]+ba/b[height<=720]/best[height<=720]"
    assert worker._quality_to_youtube_stream_format("480") == "bv*[height<=480]+ba/b[height<=480]/best[height<=480]"
    assert worker._quality_to_youtube_stream_format("worst") == "worst"
    assert worker._quality_to_youtube_stream_format("unknown") == "bv*+ba/best"


def test_scan_youtube_stream_artifacts_cardinality_sidecars_and_partials(tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))
    output_base = tmp_path / "ts_20260521_120000"
    expected = [
        tmp_path / "ts_20260521_120000.info.json",
        tmp_path / "ts_20260521_120000.mp4.part",
        tmp_path / "ts_20260521_120000.ytdl",
        tmp_path / "ts_20260521_120000.mp4",
        tmp_path / "ts_20260521_120000.webm",
        tmp_path / "ts_20260521_120000.mkv",
        tmp_path / "ts_20260521_120000.ts",
    ]
    for path in expected:
        path.write_text("x", encoding="utf-8")
    (tmp_path / "ts_20260521_120000.txt").write_text("ignored", encoding="utf-8")

    artifacts = worker._scan_youtube_stream_artifacts(str(output_base))

    artifact_names = {path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for path in artifacts}
    assert artifact_names == {path.name for path in expected}


@pytest.mark.asyncio
async def test_report_download_failure_alert_reference_youtube_stream_error_kind(monkeypatch, tmp_path):
    worker = VideoDownloadWorker(output_dir=str(tmp_path))
    report = AsyncMock()
    monkeypatch.setattr(worker_module, "report_video_failure_alert", report)
    request = SimpleNamespace(
        id=17,
        download_type=VideoDownload.TYPE_YOUTUBE_STREAM,
        url="https://www.youtube.com/live/example",
        retry_count=2,
    )

    await worker._report_download_failure_alert(
        request,
        {"error_kind": "youtube_live_ffmpeg_failed"},
        "YouTube Live 녹화/병합 실패",
    )

    report.assert_awaited_once_with(
        request_id=17,
        failure_kind="youtube_live_ffmpeg_failed",
        error_summary="YouTube Live 녹화/병합 실패",
        url="https://www.youtube.com/live/example",
        attempt=2,
    )
