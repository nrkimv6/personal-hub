"""Notes bootstrap live-server E2E tests."""

import uuid

import httpx
import pytest

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8001"


def _get(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    try:
        return httpx.get(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def _post(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    try:
        return httpx.post(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def _delete(path: str, timeout: int = 5, **kwargs) -> httpx.Response:
    try:
        return httpx.delete(BASE_URL + path, timeout=timeout, **kwargs)
    except httpx.ConnectError:
        pytest.fail("실서버 미기동 — localhost:8001 연결 불가")


def test_notes_bootstrap_first_and_second_request_return_200():
    """첫 요청과 동일 프로세스 재요청 모두 bootstrap 오류 없이 통과해야 한다."""
    first = _get("/api/notes")
    second = _get("/api/notes")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert "items" in first.json()
    assert "items" in second.json()


def test_notes_bootstrap_create_archive_round_trip():
    """live 서버에서 create -> archive -> archive list 흐름이 bootstrap 오류 없이 이어져야 한다."""
    unique = uuid.uuid4().hex[:12]
    title = f"bootstrap-e2e-{unique}"
    created_note_id = None
    archive_id = None

    try:
        created = _post(
            "/api/notes",
            json={"title": title, "content": "bootstrap e2e smoke"},
        )
        assert created.status_code == 201, created.text
        created_payload = created.json()
        created_note_id = created_payload["id"]

        archived = _post(f"/api/notes/{created_note_id}/archive")
        assert archived.status_code == 200, archived.text
        archive_payload = archived.json()
        archive_id = archive_payload["id"]
        assert archive_payload["original_id"] == created_note_id

        archive_list = _get("/api/notes/archive")
        assert archive_list.status_code == 200, archive_list.text
        archive_original_ids = [item["original_id"] for item in archive_list.json()["items"]]
        assert created_note_id in archive_original_ids
    finally:
        if archive_id is not None:
            _delete(f"/api/notes/archive/{archive_id}")
