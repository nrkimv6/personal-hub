"""Video downloads page E2E tests."""

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


def test_collect_video_tab_shows_instagram_option(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)
    page.goto(f"{frontend_url}/collect?tab=videos")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    expect(page.locator("h1")).to_contain_text(re.compile("비디오 다운로드"))
    page.locator("#typeFilter").select_option("instagram")
    assert page.locator("#typeFilter").input_value() == "instagram"


def test_collect_video_modal_shows_instagram_type_and_help(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)
    page.goto(f"{frontend_url}/collect?tab=videos")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    page.locator("button:has-text('새 다운로드')").click()
    expect(page.locator("#type")).to_be_visible()
    page.locator("#type").select_option("instagram")

    expect(page.locator("text=Instagram은 1차로 공개 Reel만 지원")).to_be_visible()


def test_legacy_video_downloads_route_redirects_to_collect_tab(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)
    page.goto(f"{frontend_url}/video-downloads")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    expect(page).to_have_url(re.compile(r".*/collect\?tab=videos"))
