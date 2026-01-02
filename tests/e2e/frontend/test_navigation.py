"""
프론트엔드 네비게이션 E2E 테스트

주요 페이지 로드 및 기본 네비게이션을 테스트합니다.
"""

import pytest
from playwright.sync_api import Page, expect


class TestPageLoad:
    """페이지 로드 테스트"""

    def test_dashboard_loads(self, page: Page, frontend_url: str):
        """대시보드 페이지 로드"""
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")

        # 타이틀 확인
        expect(page).to_have_title("모니터링 시스템")

        # 메인 컨텐츠 영역 확인
        main = page.locator("main")
        expect(main).to_be_visible()

    def test_businesses_page_loads(self, page: Page, frontend_url: str):
        """업체 목록 페이지 로드"""
        page.goto(f"{frontend_url}/businesses")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title("모니터링 시스템")
        expect(page.locator("main")).to_be_visible()

    def test_naver_schedules_page_loads(self, page: Page, frontend_url: str):
        """네이버 스케줄 페이지 로드"""
        page.goto(f"{frontend_url}/naver/schedules")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title("모니터링 시스템")
        expect(page.locator("main")).to_be_visible()

    def test_instagram_page_loads(self, page: Page, frontend_url: str):
        """Instagram 페이지 로드"""
        page.goto(f"{frontend_url}/instagram")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title("모니터링 시스템")
        expect(page.locator("main")).to_be_visible()


class TestSidebar:
    """사이드바 네비게이션 테스트"""

    def test_sidebar_visible_on_desktop(self, page: Page, frontend_url: str):
        """데스크톱에서 사이드바 표시"""
        # 데스크톱 뷰포트 설정
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")

        # 사이드바 확인
        sidebar = page.locator("aside")
        expect(sidebar).to_be_visible()

    def test_sidebar_navigation(self, page: Page, frontend_url: str):
        """사이드바를 통한 페이지 이동"""
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")

        # 업체 메뉴 클릭 (있는 경우)
        businesses_link = page.locator("aside a[href='/businesses']")
        if businesses_link.count() > 0:
            businesses_link.click()
            page.wait_for_load_state("networkidle")
            expect(page).to_have_url(f"{frontend_url}/businesses")


class TestMobileNavigation:
    """모바일 네비게이션 테스트"""

    def test_mobile_menu_toggle(self, page: Page, frontend_url: str):
        """모바일에서 메뉴 토글"""
        # 모바일 뷰포트 설정
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")

        # 모바일 헤더 확인
        header = page.locator("header.lg\\:hidden")
        expect(header).to_be_visible()

        # 메뉴 버튼 클릭
        menu_button = header.locator("button[aria-label='메뉴 열기']")
        expect(menu_button).to_be_visible()
        menu_button.click()

        # 사이드바 표시 확인
        sidebar = page.locator("aside")
        expect(sidebar).to_be_visible()
