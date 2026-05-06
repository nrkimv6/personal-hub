"""
file-search preview API 테스트

GET /api/v1/file-search/preview의 HTTP contract(200/404/413/415)를 고정합니다.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.file_search.routes import router as file_search_router
from app.modules.file_search.services.search_service import MAX_PREVIEW_BYTES


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(file_search_router)
    return TestClient(app)


def test_preview_http_right_returns_200_payload(client, tmp_path: Path):
    target = tmp_path / "hello.md"
    target.write_text("# Title\nHello\n", encoding="utf-8")

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 200
    data = resp.json()

    assert data["file_path"] == str(target)
    assert data["file_name"] == "hello.md"
    assert data["extension"] == "md"
    assert data["size_bytes"] == target.stat().st_size
    assert data["encoding"] in ("utf-8-sig", "utf-8")
    assert data["content"].startswith("# Title")


def test_preview_http_error_missing_file_returns_404(client, tmp_path: Path):
    missing = tmp_path / "missing.md"
    resp = client.get("/api/v1/file-search/preview", params={"path": str(missing)})
    assert resp.status_code == 404


def test_preview_http_error_directory_path_returns_404(client, tmp_path: Path):
    resp = client.get("/api/v1/file-search/preview", params={"path": str(tmp_path)})
    assert resp.status_code == 404


def test_preview_http_error_oversized_returns_413(client, tmp_path: Path):
    target = tmp_path / "big.txt"
    target.write_bytes(b"a" * (MAX_PREVIEW_BYTES + 1))

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 413


def test_preview_http_error_unsupported_extension_returns_415(client, tmp_path: Path):
    target = tmp_path / "data.bin"
    target.write_text("hello", encoding="utf-8")

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 415
