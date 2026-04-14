"""LLM bootstrap API HTTP tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.routes.llm_routes import router as llm_router


_app = FastAPI()
_app.include_router(llm_router)


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    _app.dependency_overrides[get_db] = override_get_db
    with TestClient(_app) as c:
        yield c
    _app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cleanup_requests(test_db_session):
    test_db_session.execute(text("DELETE FROM llm_requests"))
    test_db_session.commit()
    yield
    test_db_session.execute(text("DELETE FROM llm_requests"))
    test_db_session.commit()


def test_get_llm_bootstrap_forwards_filters_and_returns_batched_shape(client, monkeypatch):
    captured: dict[str, object] = {}

    def fake_get_bootstrap_data(
        self,
        status=None,
        caller_type=None,
        requested_by=None,
        include_deleted=False,
        page=1,
        page_size=20,
        queue_name=None,
    ):
        captured.update(
            status=status,
            caller_type=caller_type,
            requested_by=requested_by,
            include_deleted=include_deleted,
            page=page,
            page_size=page_size,
            queue_name=queue_name,
        )
        return {
            "list": {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 1},
            "stats": {"total": 0, "pending": 0, "processing": 0, "completed": 0, "failed": 0},
            "queue_stats": {"system": {"pending": 0, "processing": 0}, "utility": {"pending": 0, "processing": 0}},
            "worker_status": {"status": "no_worker", "message": "활성 워커 없음"},
        }

    monkeypatch.setattr(LLMService, "get_bootstrap_data", fake_get_bootstrap_data)

    resp = client.get(
        "/api/v1/llm/bootstrap?status=pending,processing&caller_type=test&requested_by=manual&queue_name=utility&page=2&page_size=5"
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["page"] == 2
    assert data["list"]["page_size"] == 5
    assert data["stats"]["total"] == 0
    assert data["worker_status"]["status"] == "no_worker"
    assert captured == {
        "status": "pending,processing",
        "caller_type": "test",
        "requested_by": "manual",
        "include_deleted": False,
        "page": 2,
        "page_size": 5,
        "queue_name": "utility",
    }


def test_get_llm_bootstrap_serializes_nested_request_list_shape(client, monkeypatch):
    def fake_get_bootstrap_data(
        self,
        status=None,
        caller_type=None,
        requested_by=None,
        include_deleted=False,
        page=1,
        page_size=20,
        queue_name=None,
    ):
        return {
            "list": {
                "items": [
                    {
                        "id": 101,
                        "caller_type": "test",
                        "caller_id": "bootstrap-pending",
                        "status": "pending",
                        "requested_by": "manual",
                        "request_source": None,
                        "provider": "claude",
                        "model": "",
                        "mode": "single",
                        "queue_name": "system",
                        "requested_at": None,
                        "processed_at": None,
                        "result": None,
                        "error_message": None,
                        "retry_count": 0,
                        "prompt": "pending",
                        "cli_options": None,
                    }
                ],
                "total": 1,
                "page": page,
                "page_size": page_size,
                "pages": 1,
            },
            "stats": {"total": 1, "pending": 1, "processing": 0, "completed": 0, "failed": 0},
            "queue_stats": {"system": {"pending": 1, "processing": 0}, "utility": {"pending": 0, "processing": 0}},
            "worker_status": {"status": "healthy", "worker_id": "worker-1", "state": "idle"},
        }

    monkeypatch.setattr(LLMService, "get_bootstrap_data", fake_get_bootstrap_data)

    resp = client.get("/api/v1/llm/bootstrap?page=3&page_size=10")

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["total"] == 1
    assert data["list"]["items"][0]["caller_id"] == "bootstrap-pending"
    assert data["list"]["items"][0]["queue_name"] == "system"
    assert data["queue_stats"]["system"]["pending"] == 1
    assert data["worker_status"]["state"] == "idle"


def test_get_llm_bootstrap_treats_blank_result_and_cli_options_as_null(client, monkeypatch):
    def fake_get_bootstrap_data(
        self,
        status=None,
        caller_type=None,
        requested_by=None,
        include_deleted=False,
        page=1,
        page_size=20,
        queue_name=None,
    ):
        return {
            "list": {
                "items": [
                    {
                        "id": 203,
                        "caller_type": "test",
                        "caller_id": "bootstrap-empty",
                        "status": "failed",
                        "requested_by": "manual",
                        "request_source": "manual_test",
                        "provider": "claude",
                        "model": "",
                        "mode": "single",
                        "queue_name": "utility",
                        "requested_at": None,
                        "processed_at": None,
                        "result": "",
                        "error_message": "boom",
                        "retry_count": 0,
                        "prompt": "empty",
                        "cli_options": "",
                    }
                ],
                "total": 1,
                "page": page,
                "page_size": page_size,
                "pages": 1,
            },
            "stats": {"total": 1, "pending": 0, "processing": 0, "completed": 0, "failed": 1},
            "queue_stats": {"system": {"pending": 0, "processing": 0}, "utility": {"pending": 0, "processing": 0}},
            "worker_status": {"status": "healthy", "worker_id": "worker-1", "state": "idle"},
        }

    monkeypatch.setattr(LLMService, "get_bootstrap_data", fake_get_bootstrap_data)

    resp = client.get("/api/v1/llm/bootstrap?status=failed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["items"][0]["result"] is None
    assert data["list"]["items"][0]["cli_options"] is None


def test_get_llm_bootstrap_silently_nulls_invalid_json_fields(client, monkeypatch):
    def fake_get_bootstrap_data(
        self,
        status=None,
        caller_type=None,
        requested_by=None,
        include_deleted=False,
        page=1,
        page_size=20,
        queue_name=None,
    ):
        return {
            "list": {
                "items": [
                    {
                        "id": 204,
                        "caller_type": "test",
                        "caller_id": "bootstrap-invalid",
                        "status": "completed",
                        "requested_by": "manual",
                        "request_source": "manual_test",
                        "provider": "claude",
                        "model": "",
                        "mode": "single",
                        "queue_name": "utility",
                        "requested_at": None,
                        "processed_at": None,
                        "result": "{invalid-json}",
                        "error_message": None,
                        "retry_count": 0,
                        "prompt": "invalid",
                        "cli_options": "{invalid-json}",
                    }
                ],
                "total": 1,
                "page": page,
                "page_size": page_size,
                "pages": 1,
            },
            "stats": {"total": 1, "pending": 0, "processing": 0, "completed": 1, "failed": 0},
            "queue_stats": {"system": {"pending": 0, "processing": 0}, "utility": {"pending": 0, "processing": 0}},
            "worker_status": {"status": "healthy", "worker_id": "worker-1", "state": "idle"},
        }

    monkeypatch.setattr(LLMService, "get_bootstrap_data", fake_get_bootstrap_data)

    resp = client.get("/api/v1/llm/bootstrap?status=completed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["items"][0]["result"] is None
    assert data["list"]["items"][0]["cli_options"] is None
