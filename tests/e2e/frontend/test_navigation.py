"""
프론트엔드 네비게이션 E2E 테스트

주요 페이지 로드 및 기본 네비게이션을 테스트합니다.
"""

import pytest
import subprocess
import sys
import re
from pathlib import Path
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _run_restart_frontend_admin() -> subprocess.CompletedProcess:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "browser_workers.py"
    return subprocess.run(
        [sys.executable, str(script), "restart-frontend"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )


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

    def test_naver_page_loads(self, page: Page, frontend_url: str):
        """네이버 예약 페이지 로드"""
        page.goto(f"{frontend_url}/naver")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title("모니터링 시스템")
        expect(page.locator("main")).to_be_visible()

    def test_activity_page_loads(self, page: Page, frontend_url: str):
        """문화/체육센터 페이지 로드"""
        page.goto(f"{frontend_url}/activity")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_title("모니터링 시스템")
        expect(page.locator("main")).to_be_visible()

    def test_collect_page_loads(self, page: Page, frontend_url: str):
        """수집 관리 페이지 로드"""
        page.goto(f"{frontend_url}/collect")
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

        # 네이버 예약 메뉴 클릭
        naver_link = page.locator("aside a[href='/naver']")
        naver_link.click()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{frontend_url}/naver")

    def test_dashboard_loads_after_restart_frontend_admin_e2e(self, page: Page, frontend_url: str):
        """CLI restart-frontend 직후 /dashboard가 정상 로드되어야 한다."""
        result = _run_restart_frontend_admin()
        assert result.returncode in (0, 1)

        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        expect(page).to_have_title(re.compile(r"(모니터링 시스템|통합 대시보드)"))
        expect(page.locator("main")).to_be_visible()

    def test_sidebar_navigation_after_restart_frontend_admin_e2e(self, page: Page, frontend_url: str):
        """CLI restart-frontend 직후 사이드바 내비게이션이 동작해야 한다."""
        result = _run_restart_frontend_admin()
        assert result.returncode in (0, 1)

        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")

        naver_link = page.locator("aside a[href='/naver']")
        naver_link.click()
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{frontend_url}/naver")


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
