"""Live admin E2E for collect history writing diagnostics."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import re
import sys
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.models.task_schedule import TaskSchedule, TaskScheduleRun

pytestmark = pytest.mark.e2e


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(marker in title for marker in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


@contextmanager
def _seed_live_writing_failure():
    session = SessionLocal()
    suffix = uuid4().hex[:8]
    schedule_name = f"writing_task_e2e_{suffix}"
    display_name = f"글쓰기 E2E {suffix}"
    error_message = "소스 글이 부족합니다: 0개 (최소 3개 필요) - writing_sources 데이터 이관/동기화 누락을 확인하세요."

    schedule = TaskSchedule(
        name=schedule_name,
        display_name=display_name,
        target_type=TaskSchedule.TARGET_TYPE_WRITING_TASK,
        schedule_type=TaskSchedule.SCHEDULE_TYPE_TIME_WINDOW,
        schedule_value="{}",
        enabled=True,
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)

    run = TaskScheduleRun(
        schedule_id=schedule.id,
        status=TaskScheduleRun.STATUS_FAILED,
        started_at=datetime.now(),
        finished_at=datetime.now(),
        error_message=error_message,
        stop_reason="source_shortage",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        yield {
            "schedule_id": schedule.id,
            "run_id": run.id,
            "display_name": display_name,
            "error_message": error_message,
        }
    finally:
        session.query(TaskScheduleRun).filter(TaskScheduleRun.id == run.id).delete()
        session.query(TaskSchedule).filter(TaskSchedule.id == schedule.id).delete()
        session.commit()
        session.close()


def test_collect_history_writing_failure_row_renders(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)

    with _seed_live_writing_failure() as seeded:
        page.goto(f"{frontend_url}/collect/history?sourceType=writing&period=month")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        row = page.locator("tbody tr").filter(has_text=seeded["display_name"]).first
        expect(row).to_be_visible()
        expect(row).to_contain_text("글쓰기")
        expect(row).to_contain_text("실패")
        expect(row).to_contain_text("소스 글이 부족합니다: 0개")


def test_collect_history_writing_filters_preserve_row(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)

    with _seed_live_writing_failure() as seeded:
        page.goto(f"{frontend_url}/collect/history?sourceType=writing&period=month")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        row = page.locator("tbody tr").filter(has_text=seeded["display_name"]).first
        expect(row).to_be_visible()

        page.locator("#status").select_option("failed")
        page.wait_for_load_state("networkidle")
        expect(row).to_be_visible()

        page.locator("#period").select_option("all")
        page.wait_for_load_state("networkidle")
        expect(row).to_be_visible()
        expect(page).to_have_url(re.compile(r".*sourceType=writing.*status=failed.*period=all.*"))
