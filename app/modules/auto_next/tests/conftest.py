"""auto_next 테스트 공통 fixtures"""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI
import httpx

from app.modules.auto_next.routes.tasks import router as tasks_router
from app.modules.auto_next.routes.stats import router as stats_router
from app.modules.auto_next.routes.runner import router as runner_router
from app.modules.auto_next.routes.logs import router as logs_router
from app.modules.auto_next.routes.plans import router as plans_router
from app.modules.auto_next.services.state import get_state


def _create_test_app() -> FastAPI:
    """테스트용 미니 FastAPI 앱"""
    test_app = FastAPI()
    prefix = "/api/v1/auto-next"
    test_app.include_router(tasks_router, prefix=prefix)
    test_app.include_router(stats_router, prefix=prefix)
    test_app.include_router(runner_router, prefix=prefix)
    test_app.include_router(logs_router, prefix=prefix)
    test_app.include_router(plans_router, prefix=prefix)
    return test_app


_test_app = _create_test_app()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=_test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_db(tmp_path):
    """테스트용 임시 DB"""
    db_path = tmp_path / "test_tasks.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'plan_item',
            source_path TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            output_tokens INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            error_message TEXT,
            model_used TEXT
        )
    """)
    conn.execute("""
        INSERT INTO tasks (id, type, source_path, text, priority, status, created_at, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens)
        VALUES ('test-1', 'plan_item', 'test.md', 'Test task 1', 0, 'success', '2026-02-11T10:00:00', 100, 200, 50, 10)
    """)
    conn.execute("""
        INSERT INTO tasks (id, type, source_path, text, priority, status, created_at, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens)
        VALUES ('test-2', 'plan_item', 'test.md', 'Test task 2', 1, 'pending', '2026-02-11T11:00:00', 0, 0, 0, 0)
    """)
    conn.execute("""
        INSERT INTO tasks (id, type, source_path, text, priority, status, created_at, started_at, finished_at, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, error_message)
        VALUES ('test-3', 'plan_item', 'test.md', 'Test task 3', 0, 'failed', '2026-02-11T12:00:00', '2026-02-11T12:01:00', '2026-02-11T12:02:00', 50, 0, 0, 0, 'Some error')
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def patch_db(mock_db):
    with patch("app.modules.auto_next.services.db_service.db_service.db_path", mock_db):
        yield


@pytest.fixture(autouse=True)
def reset_state():
    state = get_state()
    state.reset()
    yield
    state.reset()
