from __future__ import annotations

from io import BytesIO

from PIL import Image
from sqlalchemy import text

from app.modules.slide_scanner.routers import slides as slides_router_module


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (128, 96), color=(240, 240, 240))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_upload_slide_correct_detect_meta_nullable_fields(
    slide_scanner_client,
    slide_scanner_session,
    monkeypatch,
):
    monkeypatch.setattr(
        slides_router_module.rectifier_client,
        "detect_with_meta",
        lambda _path: {
            "points": [(1.0, 1.0), (127.0, 1.0), (127.0, 95.0), (1.0, 95.0)],
            "meta": {
                "requested_engine": "dl",
                "selected_engine": "opencv",
                "confidence": 0.78,
                "fallback_reason": "model_missing",
                "selection_reason": "opencv_higher",
            },
        },
    )

    response = slide_scanner_client.post(
        "/api/v1/ss/slides/upload",
        files={"file": ("detect-meta.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["detect_meta"]["selected_engine"] == "opencv"
    assert payload["detect_meta"]["confidence"] == 0.78
    assert payload["detect_meta"]["fallback_reason"] == "model_missing"

    row = slide_scanner_session.execute(
        text(
            """
            SELECT detect_engine, detect_confidence, detect_fallback_reason
            FROM slides
            WHERE id = :id
            """
        ),
        {"id": payload["id"]},
    ).fetchone()
    assert row.detect_engine == "opencv"
    assert row.detect_confidence == 0.78
    assert row.detect_fallback_reason == "model_missing"


def test_get_slide_reference_detect_meta_persisted(
    slide_scanner_client,
    monkeypatch,
):
    monkeypatch.setattr(
        slides_router_module.rectifier_client,
        "detect_with_meta",
        lambda _path: {
            "points": [(2.0, 2.0), (126.0, 2.0), (126.0, 94.0), (2.0, 94.0)],
            "meta": {
                "requested_engine": "dl",
                "selected_engine": "dl",
                "confidence": 0.91,
                "fallback_reason": None,
                "selection_reason": "dl_higher",
            },
        },
    )

    upload_response = slide_scanner_client.post(
        "/api/v1/ss/slides/upload",
        files={"file": ("persist.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert upload_response.status_code == 200
    slide_id = upload_response.json()["id"]

    get_response = slide_scanner_client.get(f"/api/v1/ss/slides/{slide_id}")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["detect_meta"]["selected_engine"] == "dl"
    assert payload["detect_meta"]["confidence"] == 0.91
    assert payload["detect_meta"]["fallback_reason"] is None
