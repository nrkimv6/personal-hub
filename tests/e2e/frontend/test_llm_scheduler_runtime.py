"""LLM / scheduler runtime smoke tests."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _assert_no_loading_spinner(page: Page) -> None:
    expect(page.locator(".animate-spin")).to_have_count(0, timeout=15000)


class TestLlmRuntime:
    def test_llm_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str, system_mode: str):
        _skip_admin_mode_if_public(system_mode)

        page.goto(f"{frontend_url}/llm")
        page.wait_for_load_state("networkidle")

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert (
            page.get_by_text("대기열이 비어있습니다").count() > 0
            or page.get_by_text("이력이 없습니다").count() > 0
            or page.get_by_text("이력 보기").count() > 0
            or page.locator("table tbody tr").count() > 0
        ), "LLM 화면이 빈 상태로 남아있거나 목록이 렌더되지 않았습니다"


class TestSchedulerRuntime:
    def test_scheduler_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str, system_mode: str):
        _skip_admin_mode_if_public(system_mode)

        page.goto(f"{frontend_url}/scheduler")
        page.wait_for_load_state("networkidle")

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert (
            page.get_by_text("등록된 스케줄이 없습니다").count() > 0
            or page.locator("table tbody tr").count() > 0
        ), "Scheduler 화면이 빈 상태로 남아있거나 목록이 렌더되지 않았습니다"
