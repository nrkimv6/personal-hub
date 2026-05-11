from __future__ import annotations

from io import BytesIO
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["TESTING"] = "1"

pytestmark = pytest.mark.http


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (16, 16), color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def image_pdf_client(tmp_path, monkeypatch):
    from app.main import app
    from app.models.image_pdf_task import ImagePdfTask
    from app.routes import image_pdf as image_pdf_route

    engine = create_engine(f"sqlite:///{tmp_path / 'image_pdf_tasks.db'}", connect_args={"check_same_thread": False})
    ImagePdfTask.__table__.create(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[image_pdf_route.get_db] = override_get_db
    monkeypatch.setattr(image_pdf_route, "SessionLocal", Session)
    monkeypatch.setattr(image_pdf_route.settings, "IMAGE_PDF_WORK_ROOT", str(tmp_path / "work"))

    with TestClient(app) as client:
        yield client, Session, image_pdf_route

    app.dependency_overrides.pop(image_pdf_route.get_db, None)
    engine.dispose()


def _upload(client, payload: bytes | None = None, filename: str = "sample.jpg"):
    data = payload if payload is not None else _image_bytes()
    return client.post(
        "/api/v1/image-pdf/convert",
        files=[("files", (filename, BytesIO(data), "image/jpeg"))],
        data={},
    )


def test_convert_start_returns_task_id_without_pdf_bytes_R(image_pdf_client, monkeypatch):
    client, _Session, route = image_pdf_client

    def fail_direct_conversion(*_args, **_kwargs):
        raise AssertionError("start route must not synchronously convert PDF bytes")

    monkeypatch.setattr(route, "convert_images_to_pdf", fail_direct_conversion)
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client)

    assert resp.status_code == 202
    assert "application/json" in resp.headers.get("content-type", "")
    body = resp.json()
    assert body["task_id"]
    assert body["status"] == "queued"
    assert body["artifact_url"].endswith(f"/tasks/{body['task_id']}/result")


def test_convert_large_upload_still_returns_task_id_B(image_pdf_client, monkeypatch):
    client, _Session, route = image_pdf_client
    monkeypatch.setattr(route, "convert_images_to_pdf", lambda *_args, **_kwargs: b"%PDF-test")
    payload = _image_bytes(size=(2048, 2048))

    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        resp = _upload(client, payload=payload)

    assert resp.status_code == 202
    assert resp.json()["task_id"]


def test_convert_invalid_upload_returns_422_without_task_E(image_pdf_client):
    client, Session, _route = image_pdf_client

    resp = _upload(client, payload=b"", filename="empty.jpg")

    assert resp.status_code == 422
    with Session() as db:
        from app.models.image_pdf_task import ImagePdfTask

        assert db.query(ImagePdfTask).count() == 0


def test_result_endpoint_serves_completed_artifact_R(image_pdf_client, tmp_path):
    client, Session, _route = image_pdf_client
    with patch("app.routes.image_pdf.BackgroundTasks.add_task"):
        create_resp = _upload(client)
    assert create_resp.status_code == 202
    task_id = create_resp.json()["task_id"]

    output = tmp_path / "result.pdf"
    output.write_bytes(b"%PDF-test")

    from app.models.image_pdf_task import ImagePdfTask

    with Session() as db:
        task = db.query(ImagePdfTask).filter_by(task_id=task_id).first()
        assert task is not None
        task.stored_output_path = str(output)
        task.mark_completed()
        db.commit()

    result_resp = client.get(f"/api/v1/image-pdf/tasks/{task_id}/result")
    assert result_resp.status_code == 200
    assert "application/pdf" in result_resp.headers.get("content-type", "")
