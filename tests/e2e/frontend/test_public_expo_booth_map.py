import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_public_mode_if_admin(system_mode: str) -> None:
    if system_mode != "public":
        pytest.skip(f"현재 system mode={system_mode} — public E2E 스킵")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


class TestPublicExpoBoothMap:
    def test_sidebar_navigates_to_expo_booth_map(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(public_frontend_url)
        page.wait_for_load_state("networkidle")
        page.get_by_role("link", name="커피엑스포 2026").click()
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026$"))
        expect(page.get_by_role("heading", name="커피엑스포 2026")).to_be_visible()

    def test_url_restores_selected_booth_and_slot(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026?booth=A-01&slot=open-demo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("로스터스 랩")).to_be_visible()
        expect(page.get_by_role("button", name="10:30 오픈 데모")).to_have_class(re.compile("amber"))

    def test_slot_filter_dims_non_matching_booths(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="10:30 오픈 데모").click()

        expect(page.get_by_role("button", name=re.compile(r"A-01"))).to_have_class(re.compile("opacity-100"))
        expect(page.get_by_role("button", name=re.compile(r"A-02"))).to_have_class(re.compile("opacity-30"))

    def test_author_route_redirects_in_public_mode(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026$"))

    def test_events_expo_tab_redirects_back_to_online_for_public(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/events\?tab=online"))

    def test_mobile_sheet_opens_for_selected_booth(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name=re.compile(r"A-01")).click()

        expect(page.get_by_role("button", name="닫기")).to_be_visible()
        expect(page.get_by_text("오픈 빈 테이스팅")).to_be_visible()
        assert page.evaluate("() => document.body.style.overflow") == "hidden"


class TestAdminExpoAuthor:
    # Admin author/editor surfaces intentionally keep draft state local-only until save-api is introduced.
    def test_author_page_is_available_in_admin_mode(self, page: Page, frontend_url: str, system_mode: str):
        _skip_admin_mode_if_public(system_mode)

        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026/author$"))
        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작성")).to_be_visible()
        expect(page.locator('meta[name="robots"]')).to_have_attribute("content", re.compile("noindex"))

    def test_admin_events_tab_renders_expo_workspace(self, page: Page, frontend_url: str, system_mode: str):
        _skip_admin_mode_if_public(system_mode)

        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작업")).to_be_visible()
        expect(page.get_by_role("link", name="공개 부스맵 열기")).to_be_visible()
