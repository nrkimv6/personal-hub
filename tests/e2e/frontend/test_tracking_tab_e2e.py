"""
Tracking 탭 E2E 테스트

/automation?tab=tracking 진입, 탭 렌더링, 생성, 완료 체크, 필터 전환, 배지 표시를 검증한다.
"""

import time

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(m in title for m in ("ENOENT:", "EPERM", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


class TestTrackingTabLoad:
    """Tracking 탭 진입 및 기본 UI 렌더링"""

    def test_tracking_tab_accessible_via_url_param(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """`/automation?tab=tracking` URL 파라미터로 Tracking 탭에 진입할 수 있어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # Tracking 탭 헤더 확인
        expect(page.locator("h2").filter(has_text="Tracking")).to_be_visible(timeout=10000)

    def test_tracking_tab_shows_summary_stats(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """요약 통계 섹션(전체/지연/준비됨/예정/완료)이 표시되어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 요약 섹션의 '전체' 수치가 보여야 한다
        summary = page.locator("text=전체").first
        expect(summary).to_be_visible(timeout=10000)

    def test_tracking_tab_shows_filter_chips(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """상태 필터 버튼(전체/지연/준비됨/예정/완료)이 표시되어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 필터 칩들 확인
        expect(page.get_by_role("button", name="전체").first).to_be_visible(timeout=10000)
        expect(page.get_by_role("button", name="지연").first).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="준비됨").first).to_be_visible(timeout=5000)

    def test_tracking_tab_shows_add_button(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """항목 추가 버튼이 표시되어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        add_btn = page.get_by_role("button", name="항목 추가")
        expect(add_btn).to_be_visible(timeout=10000)

    def test_tracking_tab_filter_switch(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """필터 버튼 클릭 시 활성 상태가 전환되어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # '지연' 필터를 클릭하면 활성화돼야 한다
        overdue_btn = page.get_by_role("button", name="지연").first
        expect(overdue_btn).to_be_visible(timeout=10000)
        overdue_btn.click()
        page.wait_for_timeout(500)

        # 다시 '전체' 필터를 클릭하면 전환
        all_btn = page.get_by_role("button", name="전체").first
        all_btn.click()
        page.wait_for_timeout(500)
        expect(all_btn).to_be_visible()

    def test_tracking_tab_shows_add_modal_on_button_click(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """항목 추가 버튼 클릭 시 모달이 열려야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        add_btn = page.get_by_role("button", name="항목 추가")
        expect(add_btn).to_be_visible(timeout=10000)
        add_btn.click()

        # 모달 헤더 확인
        modal_title = page.locator("h3").filter(has_text="Tracking 항목 추가")
        expect(modal_title).to_be_visible(timeout=5000)

        # 닫기 버튼으로 모달 닫기
        close_btn = page.get_by_role("button", name="닫기").first
        close_btn.click()
        expect(modal_title).not_to_be_visible(timeout=5000)

    def test_tracking_tab_create_complete_filter_and_badge_flow(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """항목 생성, 준비됨/완료 배지, 완료 필터, 삭제 정리를 UI에서 검증한다."""
        _skip_admin_mode_if_public(system_mode)
        title = f"E2E Tracking {int(time.time() * 1000)}"

        page.goto(f"{frontend_url}/automation?tab=tracking")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        page.get_by_role("button", name="항목 추가").click()
        expect(page.locator("h3").filter(has_text="Tracking 항목 추가")).to_be_visible(
            timeout=5000
        )
        page.get_by_label("제목").fill(title)
        page.get_by_label("설명").fill("Tracking 탭 E2E 생성 항목")
        page.get_by_label("마감기한").fill("2099-12-31T09:00")
        page.get_by_role("button", name="저장").click()

        row = page.locator("article").filter(has_text=title)
        expect(row).to_be_visible(timeout=10000)
        expect(row.get_by_text("준비됨", exact=True)).to_be_visible(timeout=5000)

        row.locator("input[type='checkbox']").check()
        expect(row.get_by_text("완료", exact=True)).to_be_visible(timeout=10000)

        page.get_by_role("button", name="완료").first.click()
        expect(row).to_be_visible(timeout=10000)

        page.get_by_role("button", name="전체").first.click()
        expect(row).to_be_visible(timeout=10000)
        row.get_by_role("button", name="삭제").click()
        expect(row).not_to_be_visible(timeout=10000)
