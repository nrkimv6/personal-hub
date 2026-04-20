"""Writing collect-history HTTP contract tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.crawl_request import CrawlRequest
from app.models.task_schedule import TaskSchedule, TaskScheduleRun
from app.models.writing import WritingSource

API_PREFIX = "/api/v1"
pytestmark = pytest.mark.http


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    needed = {
        "task_schedules",
        "task_schedule_runs",
        "crawl_requests",
        "writing_sources",
    }
    tables = [table for name, table in Base.metadata.tables.items() if name in needed]
    Base.metadata.create_all(bind=engine, tables=tables)

    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed_failed_writing_run(test_db) -> tuple[TaskSchedule, TaskScheduleRun]:
    schedule = TaskSchedule(
        name="writing_task_http_failed",
        display_name="글쓰기 HTTP 실패",
        target_type=TaskSchedule.TARGET_TYPE_WRITING_TASK,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        schedule_value="{}",
        enabled=True,
    )
    test_db.add(schedule)
    test_db.commit()
    test_db.refresh(schedule)

    run = TaskScheduleRun(
        schedule_id=schedule.id,
        status=TaskScheduleRun.STATUS_FAILED,
        started_at=datetime(2026, 4, 20, 9, 19, 0),
        finished_at=datetime(2026, 4, 20, 9, 19, 0),
        error_message="소스 글이 부족합니다: 0개 (최소 3개 필요) - writing_sources 데이터 이관/동기화 누락을 확인하세요.",
        stop_reason="source_shortage",
        collected_count=0,
        saved_count=0,
    )
    test_db.add(run)
    test_db.commit()
    test_db.refresh(run)
    return schedule, run


def _seed_writing_sources(test_db, count: int = 3) -> None:
    for idx in range(count):
        test_db.add(
            WritingSource(
                source_type="manual",
                source_info=f"legacy-source-{idx}",
                source_url=f"https://example.com/writing/{idx}",
                content=f"본문 {idx}",
            )
        )
    test_db.commit()


def test_get_collect_history_writing_right(client, test_db):
    schedule, run = _seed_failed_writing_run(test_db)

    response = client.get(f"{API_PREFIX}/collect/history?source_type=writing&period=month")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["items"]

    found = next((item for item in data["items"] if item["id"] == run.id), None)
    assert found is not None
    assert found["history_type"] == "schedule_run"
    assert found["source_type"] == "writing"
    assert found["schedule_name"] == schedule.display_name


def test_get_collect_history_writing_failed_row_contains_diagnostics(client, test_db):
    _schedule, run = _seed_failed_writing_run(test_db)

    response = client.get(f"{API_PREFIX}/collect/history?source_type=writing&status=failed&period=month")

    assert response.status_code == 200
    data = response.json()
    found = next((item for item in data["items"] if item["id"] == run.id), None)
    assert found is not None
    assert found["status"] == "failed"
    assert found["error_message"].startswith("소스 글이 부족합니다: 0개")
    assert found["stop_reason"] == "source_shortage"


def test_post_run_writing_schedule_after_backfill_not_zero_source_failure(client, test_db):
    _seed_writing_sources(test_db, count=3)

    schedule = TaskSchedule(
        name="writing_task_http_manual",
        display_name="글쓰기 HTTP 수동 실행",
        target_type=TaskSchedule.TARGET_TYPE_WRITING_TASK,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        schedule_value="{}",
        enabled=True,
    )
    test_db.add(schedule)
    test_db.commit()
    test_db.refresh(schedule)

    response = client.post(f"{API_PREFIX}/collect/schedules/{schedule.id}/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "run_id" in payload

    run = test_db.query(TaskScheduleRun).filter(TaskScheduleRun.id == payload["run_id"]).first()
    assert run is not None
    assert run.schedule_id == schedule.id
    assert run.status == TaskScheduleRun.STATUS_RUNNING
    assert run.error_message is None
    assert run.stop_reason is None

    history = client.get(f"{API_PREFIX}/collect/history?source_type=writing&period=month")
    assert history.status_code == 200
    items = history.json()["items"]
    found = next((item for item in items if item["id"] == run.id), None)
    assert found is not None
    assert found["status"] == "running"
    assert found["error_message"] is None
    assert found["stop_reason"] is None
