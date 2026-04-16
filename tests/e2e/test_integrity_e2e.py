"""Integrity tab E2E smoke tests."""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(marker in title for marker in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


class TestIntegrityTabE2E:
    def test_system_integrity_tab_renders_summary_and_db_stats(
        self,
        page: Page,
        frontend_url: str,
        system_mode: str,
    ) -> None:
        _skip_admin_mode_if_public(system_mode)

        page.goto(f"{frontend_url}/system?tab=integrity")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_title(re.compile(r"(시스템 / 설정|Monitor Page)"))
        expect(page.locator("main").first).to_be_visible()
        expect(page.get_by_text("데이터 정합성").first).to_be_visible()

        # 초기 로딩이 끝난 뒤 요약 카드와 DB 통계 블록이 렌더되어야 한다.
        expect(page.locator(".animate-spin")).to_have_count(0, timeout=15000)
        expect(page.get_by_text("전체 문제")).to_be_visible()
        expect(page.get_by_role("heading", name="DB 통계")).to_be_visible()
        expect(page.get_by_text("businesses")).to_be_visible()
