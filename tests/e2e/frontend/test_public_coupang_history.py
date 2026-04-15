"""
공개 쿠팡 이력 E2E.

public PREVIEW(6100)에서 /coupang/history 기본 범위와 summary typography를 검증한다.
"""

import json
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

    def test_last_checked_card_uses_status_api_value(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        fixed_last_checked = "2026-04-18T12:34:56.000000+09:00"
        expected_text = page.evaluate(
            """(value) => new Date(value).toLocaleString('ko-KR', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                hour12: false
            })""",
            fixed_last_checked,
        )

        mocked_status = {
            "total_schedules": 0,
            "enabled_schedules": 0,
            "active_schedules": 0,
            "proxy_enabled": False,
            "proxy_active_count": 0,
            "worker_health": {
                "status": "healthy",
                "message": "ok",
                "updated_at": fixed_last_checked,
                "last_event_at": "2026-04-17T10:00:00.000000+09:00",
                "last_checked_at": fixed_last_checked,
            },
        }
        mocked_history = {
            "items": [],
            "summary": {
                "total": 0,
                "closed_pair_count": 0,
                "open_pair_count": 0,
                "avg_closed_duration_seconds": None
            },
            "slot_time_options": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
        }

        def _route_status(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(mocked_status))

        def _route_history(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(mocked_history))

        page.route("**/api/v1/coupang/status", _route_status)
        page.route("**/api/v1/monitoring/events/coupang-public-history*", _route_history)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{public_frontend_url}/coupang/history")
        page.wait_for_load_state("networkidle")

        last_checked_card = page.locator("div.card", has_text="마지막 확인").first
        last_checked_value = last_checked_card.locator(":scope > div").first

        expect(last_checked_card).to_be_visible()
        expect(last_checked_value).to_have_text(expected_text)
        expect(last_checked_value).not_to_have_text("-")
