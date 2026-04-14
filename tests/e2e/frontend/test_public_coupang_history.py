"""
공개 쿠팡 이력 E2E.

public PREVIEW(6100)에서 /coupang/history 기본 범위와 summary typography를 검증한다.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_public_mode_if_admin(system_mode: str) -> None:
    if system_mode != "public":
        pytest.skip(f"현재 system mode={system_mode} — public E2E 스킵")


class TestPublicCoupangHistory:
    """공개 쿠팡 이력 화면 smoke 테스트."""

    def test_history_defaults_and_summary_tone(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{public_frontend_url}/coupang/history")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/coupang/history"))
        expect(page.locator("#date-from")).to_have_value("2026-04-17")
        expect(page.locator("#date-to")).to_have_value("2026-04-19")

        recent_card = page.locator("div.card").filter(has_text="최근 감지").first
        last_checked_card = page.locator("div.card").filter(has_text="마지막 확인").first

        expect(recent_card.locator(":scope > div").first).to_have_class(re.compile(r"\btext-lg\b"))
        expect(last_checked_card.locator(":scope > div").first).to_have_class(re.compile(r"\btext-lg\b"))

        articles = page.locator("article.rounded-lg")
        assert articles.count() > 0, "공개 이력 카드가 렌더링되지 않음"
        expect(articles.first).not_to_contain_text("2026-04-17")
