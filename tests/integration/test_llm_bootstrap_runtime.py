"""LLM bootstrap runtime integration tests."""

from datetime import datetime
from sqlalchemy import MetaData, Table

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_db
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


def _ensure_llm_request_schema(test_db_session) -> None:
    columns = {
        row[1]
        for row in test_db_session.execute(text("PRAGMA table_info(llm_requests)")).fetchall()
    }
    if "claude_session_id" not in columns:
        test_db_session.execute(
            text("ALTER TABLE llm_requests ADD COLUMN claude_session_id VARCHAR(36)")
        )
        test_db_session.commit()


@pytest.fixture(autouse=True)
def cleanup_requests(test_db_session):
    _ensure_llm_request_schema(test_db_session)
    test_db_session.rollback()
    test_db_session.execute(text("DELETE FROM llm_worker_status"))
    test_db_session.execute(text("DELETE FROM llm_requests"))
    test_db_session.commit()
    yield
    test_db_session.rollback()
    test_db_session.execute(text("DELETE FROM llm_worker_status"))
    test_db_session.execute(text("DELETE FROM llm_requests"))
    test_db_session.commit()


def _seed_request(test_db_session, **overrides) -> None:
    table = Table("llm_requests", MetaData(), autoload_with=test_db_session.get_bind())
    payload = {
        "caller_type": "test",
        "caller_id": overrides.pop("caller_id", "bootstrap-runtime"),
        "prompt": overrides.pop("prompt", "runtime test"),
        "requested_at": overrides.pop("requested_at", datetime.now()),
        "requested_by": overrides.pop("requested_by", "manual"),
        "request_source": overrides.pop("request_source", "manual_test"),
        "provider": overrides.pop("provider", "claude"),
        "model": overrides.pop("model", ""),
        "status": overrides.pop("status", "completed"),
        "processed_at": overrides.pop("processed_at", datetime.now()),
        "result": overrides.pop("result", '{"ok": true}'),
        "error_message": overrides.pop("error_message", None),
        "retry_count": overrides.pop("retry_count", 0),
        "cli_options": overrides.pop("cli_options", '{"cwd": "D:/work/project/tools/monitor-page"}'),
        "queue_name": overrides.pop("queue_name", "utility"),
        "mode": overrides.pop("mode", "single"),
        **overrides,
    }
    filtered_payload = {key: value for key, value in payload.items() if key in table.c}
    test_db_session.execute(table.insert().values(**filtered_payload))
    test_db_session.commit()


def test_llm_bootstrap_parses_real_db_json_fields(client, test_db_session):
    _seed_request(
        test_db_session,
        caller_id="bootstrap-runtime-json",
        status="completed",
        result='{"answer": 42, "items": ["a", "b"]}',
        cli_options='{"cwd": "D:/work/project/tools/monitor-page", "parse_json": true}',
    )

    resp = client.get("/api/v1/llm/bootstrap?status=completed&page=1&page_size=20")

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["total"] == 1
    item = data["list"]["items"][0]
    assert item["caller_id"] == "bootstrap-runtime-json"
    assert item["result"] == {"answer": 42, "items": ["a", "b"]}
    assert item["cli_options"] == {
        "cwd": "D:/work/project/tools/monitor-page",
        "parse_json": True,
    }


def test_llm_bootstrap_nulls_invalid_json_fields(client, test_db_session):
    _seed_request(
        test_db_session,
        caller_id="bootstrap-runtime-invalid",
        status="failed",
        result="{invalid-json}",
        cli_options="{invalid-json}",
        error_message="boom",
    )

    resp = client.get("/api/v1/llm/bootstrap?status=failed")

    assert resp.status_code == 200
    data = resp.json()
    assert data["list"]["total"] == 1
    item = data["list"]["items"][0]
    assert item["caller_id"] == "bootstrap-runtime-invalid"
    assert item["result"] is None
    assert item["cli_options"] is None
