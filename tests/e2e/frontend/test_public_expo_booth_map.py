import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect

pytestmark = pytest.mark.e2e


def _skip_public_mode_if_admin(system_mode: str) -> None:
    if system_mode != "public":
        pytest.skip(f"현재 system mode={system_mode} — public E2E 스킵")


def _seed_admin_expo_draft(page: Page) -> None:
    export_record = Path(__file__).resolve().parents[3] / "data" / "expo" / "coffee-expo-2026" / "export-record.json"
    export_record.unlink(missing_ok=True)


def _hydrate_admin_expo_draft(page: Page) -> None:
    page.evaluate(
        """
        () => {
          const payload = {
            prefix: 'Z-',
            startNumber: 1,
            currentNumber: 2,
            padLength: 2,
            step: 1,
            drafts: [
              {
                name: 'Z-01',
                pin: { xNorm: 0.12, yNorm: 0.34 },
                createdAt: '2026-04-20T15:00:00+09:00'
              }
            ]
          };
          localStorage.setItem('expo:coffee-expo-2026:draft', JSON.stringify(payload));
        }
        """
    )
    page.reload()
    page.wait_for_load_state("networkidle")


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

        expect(page.get_by_text("싱글 오리진 라인업과 현장 로스팅 샘플링을 진행합니다.").first).to_be_visible()
        expect(page.get_by_role("button", name="10:30 오픈 데모")).to_have_class(re.compile("amber"))

    def test_slot_filter_dims_non_matching_booths(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="10:30 오픈 데모").click()

        expect(page.locator('button[aria-label="A-01 로스터스 랩"]')).to_have_class(re.compile("opacity-100"))
        expect(page.locator('button[aria-label="A-02 밀크 크래프트"]')).to_have_class(re.compile("opacity-30"))

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
        page.locator('button[aria-label="A-01 로스터스 랩"]').click()

        expect(page.get_by_role("button", name="닫기", exact=True)).to_be_visible()
        expect(page.get_by_role("dialog").get_by_text("오픈 빈 테이스팅")).to_be_visible()
        assert page.evaluate("() => document.body.style.overflow") == "hidden"


class TestAdminExpoAuthor:
    # Admin author/editor surfaces intentionally keep draft state local-only until save-api is introduced.
    def test_author_page_is_available_in_admin_mode(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026/author$"))
        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작성")).to_be_visible()
        expect(page.locator('meta[name="robots"]')).to_have_attribute("content", re.compile("noindex"))

    def test_admin_events_tab_renders_expo_workspace(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작업")).to_be_visible()
        expect(page.get_by_role("link", name="공개 부스맵 열기")).to_be_visible()

    def test_admin_events_tab_renders_pipeline_and_collection_sections(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="소스 파이프라인 상태")).to_be_visible()
        expect(page.get_by_role("heading", name="수집 현황과 export 흐름")).to_be_visible()

    def test_admin_export_cta_shows_success_feedback(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        export_button = page.get_by_role("button", name="Export JSON (1)")
        expect(export_button).to_be_enabled()
        export_button.click()

        expect(page.get_by_text("1개 draft를 복사하고 export 기록을 저장했습니다.")).to_be_visible()
        assert "coffee-expo-2026" in page.evaluate("() => navigator.clipboard.readText()")

    def test_admin_export_cta_updates_last_exported_timestamp(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        before = page.get_by_text("최근 export:", exact=False)
        expect(before).to_contain_text("기록 없음")

        page.get_by_role("button", name="Export JSON (1)").click()

        after = page.get_by_text("최근 export:", exact=False)
        expect(after).not_to_contain_text("기록 없음")

    def test_admin_export_keeps_unknown_publish_badge_placeholder(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        status = page.get_by_text("publish 상태: unknown")
        expect(status).to_be_visible()

        page.get_by_role("button", name="Export JSON (1)").click()

        expect(status).to_be_visible()

    def test_public_expo_page_does_not_render_admin_operations_sections(
        self, page: Page, public_frontend_url: str, system_mode: str
    ):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="소스 파이프라인 상태")).to_have_count(0)
        expect(page.get_by_role("heading", name="수집 현황과 export 흐름")).to_have_count(0)
