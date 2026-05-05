"""LLM / scheduler runtime smoke tests."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _assert_no_loading_spinner(page: Page) -> None:
    expect(page.locator(".animate-spin")).to_have_count(0, timeout=15000)


def _wait_for_runtime_page(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("main").first).to_be_visible(timeout=15000)


class TestLlmRuntime:
    def test_llm_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/llm")
        _wait_for_runtime_page(page)

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert (
            page.get_by_text("대기열이 비어있습니다").count() > 0
            or page.get_by_text("이력이 없습니다").count() > 0
            or page.get_by_text("이력 보기").count() > 0
            or page.locator("table tbody tr").count() > 0
        ), "LLM 화면이 빈 상태로 남아있거나 목록이 렌더되지 않았습니다"


class TestSchedulerRuntime:
    def test_scheduler_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/scheduler")
        _wait_for_runtime_page(page)

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert page.get_by_text("해석:").count() > 0, "Scheduler 화면에서 해석 요약이 렌더되지 않았습니다"


class TestSystemSettingsRuntime:
    def test_system_settings_exposes_scheduler_contract(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/system?tab=settings")
        _wait_for_runtime_page(page)
        page.get_by_text("AI 기본값").click()

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        expect(page.get_by_text("최근 scheduler provider")).to_be_visible()
        expect(page.get_by_text("LLMWorker 기본값")).to_be_visible()
        expect(page.get_by_text("요청값 미지정 시 caller별 기본 provider/model을 적용합니다.")).to_be_visible()
        expect(page.get_by_text("plan_requirements_sync")).to_be_visible()
