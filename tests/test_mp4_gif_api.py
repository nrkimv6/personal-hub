from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.models.mp4_gif_task import Mp4GifTask
from app.routes import mp4_gif as mp4_gif_routes
from app.routes.mp4_gif import router as mp4_gif_router
from app.services import mp4_gif_service


@pytest.fixture()
def mp4_gif_api_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Session]]:
    db_path = tmp_path / "mp4_gif_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    original_work_root = mp4_gif_service.settings.MP4_GIF_WORK_ROOT
    original_max_upload_mb = mp4_gif_service.settings.MP4_GIF_MAX_UPLOAD_MB
    mp4_gif_service.settings.MP4_GIF_WORK_ROOT = str(tmp_path / "work_root")
    mp4_gif_service.settings.MP4_GIF_MAX_UPLOAD_MB = 5
    monkeypatch.setattr(mp4_gif_routes, "SessionLocal", SessionLocal)
    monkeypatch.setattr(mp4_gif_routes, "cleanup_expired_workdirs", lambda: 0)

    app = FastAPI()
    app.include_router(mp4_gif_router)

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        mp4_gif_service.settings.MP4_GIF_WORK_ROOT = original_work_root
        mp4_gif_service.settings.MP4_GIF_MAX_UPLOAD_MB = original_max_upload_mb


def test_create_task_right_returns_202(
    mp4_gif_api_context: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
):
    client, _session = mp4_gif_api_context

    def fake_run_ffmpeg_conversion(_input_path: Path, output_path: Path, _fps: int):
        output_path.write_bytes(b"GIF89a")
        return None

    monkeypatch.setattr(mp4_gif_routes, "run_ffmpeg_conversion", fake_run_ffmpeg_conversion)

    response = client.post(
        "/api/v1/mp4-gif/tasks",
        files={"file": ("sample.mp4", b"mp4-data", "video/mp4")},
        data={"fps": "10"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"]


def test_create_task_error_rejects_non_mp4(mp4_gif_api_context: tuple[TestClient, Session]):
    client, _session = mp4_gif_api_context

    response = client.post(
        "/api/v1/mp4-gif/tasks",
        files={"file": ("sample.txt", b"not-mp4", "text/plain")},
        data={"fps": "10"},
    )

    assert response.status_code == 400
    assert "MP4" in response.json()["detail"]


def test_get_task_existence_404(mp4_gif_api_context: tuple[TestClient, Session]):
    client, _session = mp4_gif_api_context

    response = client.get("/api/v1/mp4-gif/tasks/nonexistent")
    assert response.status_code == 404


def test_result_returns_409_before_completion(mp4_gif_api_context: tuple[TestClient, Session]):
    client, session = mp4_gif_api_context
    work_dir = Path(mp4_gif_service.settings.MP4_GIF_WORK_ROOT)
    work_dir.mkdir(parents=True, exist_ok=True)
    task = Mp4GifTask(
        task_id="queued-task",
        status=Mp4GifTask.STATUS_QUEUED,
        source_name="queued.mp4",
        stored_input_path=str(work_dir / "queued.mp4"),
        stored_output_path=str(work_dir / "queued.gif"),
        fps=10,
    )
    session.add(task)
    session.commit()

    response = client.get("/api/v1/mp4-gif/tasks/queued-task/result")
    assert response.status_code == 409


def test_completed_task_result_downloads_gif(
    mp4_gif_api_context: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
):
    client, _session = mp4_gif_api_context

    def fake_run_ffmpeg_conversion(_input_path: Path, output_path: Path, _fps: int):
        output_path.write_bytes(b"GIF89a")
        return None

    monkeypatch.setattr(mp4_gif_routes, "run_ffmpeg_conversion", fake_run_ffmpeg_conversion)

    created = client.post(
        "/api/v1/mp4-gif/tasks",
        files={"file": ("sample.mp4", b"mp4-data", "video/mp4")},
        data={"fps": "8"},
    )
    task_id = created.json()["task_id"]

    status_response = client.get(f"/api/v1/mp4-gif/tasks/{task_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"

    result_response = client.get(f"/api/v1/mp4-gif/tasks/{task_id}/result")
    assert result_response.status_code == 200
    assert result_response.headers["content-type"].startswith("image/gif")
    assert result_response.content == b"GIF89a"


def test_health_reports_missing_ffmpeg(
    mp4_gif_api_context: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
):
    client, _session = mp4_gif_api_context
    monkeypatch.setattr(mp4_gif_routes, "ffmpeg_health", lambda: (False, None))

    response = client.get("/api/v1/mp4-gif/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ffmpeg_ok"] is False
    assert "ffmpeg" in payload["error_message"].lower()
