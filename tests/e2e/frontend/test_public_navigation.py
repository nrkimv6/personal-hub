"""
공개 프론트엔드 네비게이션 E2E 테스트.

public PREVIEW(6100) 기준 루트 landing과 /monitoring 차단 계약을 검증한다.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_public_mode_if_admin(system_mode: str) -> None:
    if system_mode != "public":
        pytest.skip(f"현재 system mode={system_mode} — public E2E 스킵")


class TestPublicLanding:
    """공개 모드 landing/차단 테스트."""

    def test_root_redirects_to_events(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/events"))
        expect(page.locator("main").first).to_be_visible()

    def test_monitoring_redirects_to_events(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/monitoring")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/events"))
        expect(page.locator("main").first).to_be_visible()
        assert not re.search(r"403|Forbidden|Error", page.title(), re.I)
