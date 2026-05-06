from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.file_search.routes import router as file_search_router
from app.modules.file_search.services.search_service import MAX_PREVIEW_BYTES


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(file_search_router)
    return TestClient(app)


def test_preview_integration_reads_real_utf8_file(client, tmp_path: Path):
    target = tmp_path / "hello.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 200
    data = resp.json()
    assert "print('hello')" in data["content"]


def test_preview_integration_decodes_cp949_file(client, tmp_path: Path):
    target = tmp_path / "korean.txt"
    target.write_bytes("한글".encode("cp949"))

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["encoding"] == "cp949"
    assert data["content"] == "한글"


def test_preview_integration_rejects_directory_path(client, tmp_path: Path):
    resp = client.get("/api/v1/file-search/preview", params={"path": str(tmp_path)})
    assert resp.status_code == 404


def test_preview_integration_rejects_oversized_text_file(client, tmp_path: Path):
    target = tmp_path / "big.txt"
    target.write_bytes(b"a" * (MAX_PREVIEW_BYTES + 1))

    resp = client.get("/api/v1/file-search/preview", params={"path": str(target)})
    assert resp.status_code == 413
