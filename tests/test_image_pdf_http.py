from __future__ import annotations

from io import BytesIO
import os
from unittest.mock import patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

pytestmark = pytest.mark.http


@pytest.fixture
def client(test_db_session):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (16, 16), color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _upload(client, files=None, data=None):
    upload_files = files
    if upload_files is None:
        upload_files = [("files", ("sample.jpg", BytesIO(_image_bytes()), "image/jpeg"))]
    return client.post("/api/v1/image-pdf/convert", files=upload_files, data=data or {})


def test_convert_returns_pdf_R(client):
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client)
    assert resp.status_code == 202
    body = resp.json()
    assert body["task_id"]
    assert body["status"] == "queued"
    assert body["artifact_url"].endswith(f"/tasks/{body['task_id']}/result")


def test_convert_content_disposition_filename_C(client):
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client, data={"output_name": "문서.pdf"})
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    status_resp = client.get(f"/api/v1/image-pdf/tasks/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["download_filename"] == "문서.pdf"


def test_convert_default_filename_R(client):
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client)
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    status_resp = client.get(f"/api/v1/image-pdf/tasks/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["download_filename"].startswith("image-pdf-")


def test_convert_multipart_validation_E(client):
    resp = client.post("/api/v1/image-pdf/convert", data={"bw": "false"})
    assert resp.status_code == 422


def test_health_endpoint_R(client):
    resp = client.get("/api/v1/image-pdf/health")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "supported_extensions",
        "heic_supported",
        "pillow_version",
        "max_files",
        "max_per_file_mb",
        "max_total_mb",
    ):
        assert key in body


def test_convert_empty_file_E(client):
    resp = _upload(client, files=[("files", ("empty.jpg", BytesIO(b""), "image/jpeg"))])
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] in {"empty", "corrupt"}


def test_convert_unsupported_extension_E(client):
    resp = _upload(client, files=[("files", ("bad.exe", BytesIO(b"abc"), "application/octet-stream"))])
    assert resp.status_code == 415
    assert resp.json()["detail"]["error"] == "unsupported_extension"


def test_convert_corrupt_image_E(client, monkeypatch):
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client, files=[("files", ("bad.jpg", BytesIO(b"not-image"), "image/jpeg"))])
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    from app import database
    from app.routes import image_pdf as image_pdf_route

    monkeypatch.setattr(image_pdf_route, "SessionLocal", database.SessionLocal)
    image_pdf_route._run_task(task_id)
    status_resp = client.get(f"/api/v1/image-pdf/tasks/{task_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "failed"


def test_convert_heic_when_unsupported_E(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.image_pdf_service.HEIC_OK", False)
    resp = _upload(client, files=[("files", ("a.heic", BytesIO(b"heic"), "image/heic"))])
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "heic_unsupported"


def test_convert_oversize_E(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.image_pdf_service.MAX_PER_FILE_MB", 1)
    data = b"0" * (1024 * 1024 + 1)
    resp = _upload(client, files=[("files", ("large.jpg", BytesIO(data), "image/jpeg"))])
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "file_too_large"
