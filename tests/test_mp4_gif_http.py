"""T5 HTTP 통합 TC: MP4->GIF API 엔드포인트 계약 검증.

TestClient 기반 — 실서버 불필요.
"""
import io
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ["TESTING"] = "1"

from fastapi.testclient import TestClient

pytestmark = pytest.mark.http


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


_FAKE_MP4 = b"\x00" * 128
_MP4_HEADERS = {"Content-Type": "video/mp4"}


def _upload(client, data=_FAKE_MP4, filename="test.mp4", fps=10, start_seconds=None, duration_seconds=None):
    form: dict = {"fps": str(fps)}
    if start_seconds is not None:
        form["start_seconds"] = str(start_seconds)
    if duration_seconds is not None:
        form["duration_seconds"] = str(duration_seconds)
    return client.post(
        "/api/v1/mp4-gif/tasks",
        files={"file": (filename, io.BytesIO(data), "video/mp4")},
        data=form,
    )


# ─── T5-1: POST /api/v1/mp4-gif/tasks → 202 ────────────────────────────────

class TestCreateTaskHttp:
    """POST /api/v1/mp4-gif/tasks 202 계약."""

    def test_create_task_returns_202(self, client):
        """POST /tasks → 202를 반환한다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            resp = _upload(client)
        assert resp.status_code == 202

    def test_create_task_body_has_task_id(self, client):
        """POST /tasks 응답 본문에 task_id가 있다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            resp = _upload(client)
        assert resp.status_code == 202
        body = resp.json()
        assert "task_id" in body
        assert isinstance(body["task_id"], str)
        assert len(body["task_id"]) > 0


# ─── T5-2: GET /api/v1/mp4-gif/tasks/{task_id} ──────────────────────────────

class TestGetTaskStatusHttp:
    """GET /api/v1/mp4-gif/tasks/{task_id} 상태 조회 계약."""

    def test_get_task_returns_queued_status(self, client):
        """POST 직후 GET → queued 또는 running 상태를 반환한다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            create_resp = _upload(client)
        assert create_resp.status_code == 202
        task_id = create_resp.json()["task_id"]

        status_resp = client.get(f"/api/v1/mp4-gif/tasks/{task_id}")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["task_id"] == task_id
        assert body["status"] in ("queued", "running", "completed", "failed")

    def test_get_task_404_unknown(self, client):
        """존재하지 않는 task_id → 404를 반환한다."""
        resp = client.get("/api/v1/mp4-gif/tasks/non-existent-id-000")
        assert resp.status_code == 404

    def test_get_failed_task_has_error_message(self, client):
        """failed 상태 task → error_message 필드가 있다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            create_resp = _upload(client)
        assert create_resp.status_code == 202
        task_id = create_resp.json()["task_id"]

        # DB 직접 상태 조작
        from app.database import SessionLocal
        from app.models.mp4_gif_task import Mp4GifTask
        db = SessionLocal()
        try:
            task = db.query(Mp4GifTask).filter_by(task_id=task_id).first()
            if task:
                task.mark_failed("Test failure message")
                db.commit()
        finally:
            db.close()

        status_resp = client.get(f"/api/v1/mp4-gif/tasks/{task_id}")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["status"] == "failed"
        assert body["error_message"] is not None


# ─── T5-3: GET /api/v1/mp4-gif/tasks/{task_id}/result ──────────────────────

class TestGetTaskResultHttp:
    """GET /api/v1/mp4-gif/tasks/{task_id}/result 계약."""

    def test_completed_result_returns_gif_content_type(self, client, tmp_path):
        """완료 후 result → image/gif를 반환한다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            create_resp = _upload(client)
        assert create_resp.status_code == 202
        task_id = create_resp.json()["task_id"]

        gif_file = tmp_path / "output.gif"
        gif_file.write_bytes(b"GIF89a" + b"\x00" * 16)

        from app.database import SessionLocal
        from app.models.mp4_gif_task import Mp4GifTask
        db = SessionLocal()
        try:
            task = db.query(Mp4GifTask).filter_by(task_id=task_id).first()
            if task:
                task.stored_output_path = str(gif_file)
                task.mark_completed()
                db.commit()
        finally:
            db.close()

        result_resp = client.get(f"/api/v1/mp4-gif/tasks/{task_id}/result")
        assert result_resp.status_code == 200
        assert "image/gif" in result_resp.headers.get("content-type", "")


# ─── T5-4: GET /api/v1/mp4-gif/health ──────────────────────────────────────

class TestHealthHttp:
    """GET /api/v1/mp4-gif/health 계약."""

    def test_health_ffmpeg_not_found_wording(self, client):
        """ffmpeg 미설치 시 error_message에 경고 문구가 포함된다."""
        with patch("app.services.mp4_gif_service.shutil.which", return_value=None):
            resp = client.get("/api/v1/mp4-gif/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ffmpeg_ok"] is False
        assert "ffmpeg" in (body.get("error_message") or "").lower()

    def test_health_ffmpeg_found(self, client):
        """ffmpeg 설치 시 ffmpeg_ok=True."""
        with patch("app.services.mp4_gif_service.shutil.which", return_value="/usr/bin/ffmpeg"):
            resp = client.get("/api/v1/mp4-gif/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ffmpeg_ok"] is True


# ─── trim TC (Phase T1, item 17) ──────────────────────────────────────────────

class TestTrimParamsHttp:
    """trim 파라미터 HTTP 계약 검증 — root app 수준 보장."""

    def test_create_task_with_trim_params_returns_202(self, client):
        """Right: start_seconds=3, duration_seconds=7 POST가 202를 반환한다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            resp = _upload(client, start_seconds=3, duration_seconds=7)
        assert resp.status_code == 202
        assert resp.json().get("task_id")

    def test_create_task_negative_start_returns_400(self, client):
        """Error: start_seconds=-1이면 400을 반환한다."""
        resp = _upload(client, start_seconds=-1)
        assert resp.status_code == 400

    def test_create_task_zero_duration_returns_400(self, client):
        """Error: duration_seconds=0이면 400을 반환한다."""
        resp = _upload(client, duration_seconds=0)
        assert resp.status_code == 400

    def test_get_task_status_includes_trim_fields(self, client):
        """Right: 상태 응답 JSON에 start_seconds, duration_seconds가 포함된다."""
        with patch("app.routes.mp4_gif.BackgroundTasks.add_task"):
            create_resp = _upload(client, start_seconds=2.5, duration_seconds=5.0)
        assert create_resp.status_code == 202
        task_id = create_resp.json()["task_id"]

        status_resp = client.get(f"/api/v1/mp4-gif/tasks/{task_id}")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert "start_seconds" in body
        assert "duration_seconds" in body
        assert abs(body["start_seconds"] - 2.5) < 0.01
        assert abs(body["duration_seconds"] - 5.0) < 0.01
