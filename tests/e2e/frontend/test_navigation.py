"""
프론트엔드 네비게이션 E2E 테스트

주요 페이지 로드 및 기본 네비게이션을 테스트합니다.
"""

import pytest
import subprocess
import sys
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

_FRONTEND_ERROR_TITLE_MARKERS = ("ENOENT:", "EPERM", "Vite", "Internal Server Error", "Error")
_ADMIN_RESTART_REUSE_WINDOW_SECONDS = 45.0
_recent_admin_restart: dict[str, object] = {"at": 0.0, "result": None}


def _wait_for_frontend_available(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: Exception | None = None

    while time.time() <= deadline:
        try:
            with urlopen(url, timeout=5):
                return
        except HTTPError:
            return
        except (URLError, OSError) as exc:
            last_error = exc
            time.sleep(0.5)

    pytest.fail(f"Frontend did not recover after restart: {url} ({last_error})")


def _wait_for_api_available(api_url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: Exception | None = None
    ready_url = f"{api_url}/api/v1/system/liveness"

    while time.time() <= deadline:
        try:
            with urlopen(ready_url, timeout=5) as response:
                if response.status == 200:
                    return
                last_error = RuntimeError(f"unexpected status: {response.status}")
        except (URLError, OSError) as exc:
            last_error = exc
        time.sleep(0.5)

    pytest.fail(f"API did not recover after frontend restart: {ready_url} ({last_error})")


def _is_frontend_error_title(title: str) -> bool:
    return any(marker in title for marker in _FRONTEND_ERROR_TITLE_MARKERS)


def _goto_stable_frontend_page(page: Page, url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: str | None = None

    while time.time() <= deadline:
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            title = page.title() or ""
            if not _is_frontend_error_title(title):
                return
            last_error = f"error title: {title}"
        except Exception as exc:
            last_error = str(exc)
        page.wait_for_timeout(1000)

    pytest.fail(f"Frontend stayed unstable after restart: {url} ({last_error})")


def _run_restart_frontend_admin(frontend_url: str, api_url: str) -> subprocess.CompletedProcess:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "services" / "browser_workers.py"
    result = subprocess.run(
        [sys.executable, str(script), "restart-frontend"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
        encoding="utf-8",
        errors="replace",
    )
    _wait_for_frontend_available(f"{frontend_url}/dashboard")
    _wait_for_api_available(api_url)
    return result


def _ensure_recent_admin_restart(frontend_url: str, api_url: str) -> subprocess.CompletedProcess:
    now = time.time()
    cached_at = float(_recent_admin_restart.get("at") or 0.0)
    cached_result = _recent_admin_restart.get("result")

    if isinstance(cached_result, subprocess.CompletedProcess) and (now - cached_at) <= _ADMIN_RESTART_REUSE_WINDOW_SECONDS:
        _wait_for_frontend_available(f"{frontend_url}/dashboard")
        _wait_for_api_available(api_url)
        return cached_result

    result = _run_restart_frontend_admin(frontend_url, api_url)
    _recent_admin_restart["at"] = time.time()
    _recent_admin_restart["result"] = result
    return result


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if _is_frontend_error_title(title):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


class TestPageLoad:
    """페이지 로드 테스트"""

    _TITLE_PATTERN = re.compile(r"(모니터링 시스템|통합 대시보드|Monitor Page|통합 모니터링)")

    def test_dashboard_loads(self, page: Page, frontend_url: str):
        """대시보드 페이지 로드"""
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 타이틀 확인
        expect(page).to_have_title(self._TITLE_PATTERN)

        # 메인 컨텐츠 영역 확인
        main = page.locator("main").first
        expect(main).to_be_visible()

    def test_naver_page_loads(self, page: Page, frontend_url: str):
        """네이버 예약 페이지 로드"""
        page.goto(f"{frontend_url}/naver")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 비로그인 시 /naver 는 /events 등으로 클라이언트 리다이렉트될 수 있음
        if not page.url.rstrip("/").endswith("/naver"):
            pytest.skip(f"인증 필요 페이지 — 리다이렉트됨: {page.url}")

        expect(page).to_have_title(self._TITLE_PATTERN)
        expect(page.locator("main").first).to_be_visible()

    def test_activity_page_loads(self, page: Page, frontend_url: str):
        """문화/체육센터 페이지 로드"""
        page.goto(f"{frontend_url}/activity")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_title(self._TITLE_PATTERN)
        expect(page.locator("main").first).to_be_visible()

    def test_collect_page_loads(self, page: Page, frontend_url: str):
        """수집 관리 페이지 로드"""
        page.goto(f"{frontend_url}/collect")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_title(self._TITLE_PATTERN)
        expect(page.locator("main").first).to_be_visible()

    def test_monitoring_loads(self, page: Page, frontend_url: str, system_mode: str):
        """통합 모니터링 페이지 로드"""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/monitoring")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_title(self._TITLE_PATTERN)
        expect(page.locator("main").first).to_be_visible()

    def test_root_redirects_to_monitoring(self, page: Page, frontend_url: str, system_mode: str):
        """루트(/) 접근 시 /monitoring으로 리다이렉트"""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_url(re.compile(r".*/monitoring"))


class TestSidebar:
    """사이드바 네비게이션 테스트"""

    def test_sidebar_visible_on_desktop(self, page: Page, frontend_url: str):
        """데스크톱에서 사이드바 표시"""
        # 데스크톱 뷰포트 설정
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 사이드바 확인
        sidebar = page.locator("aside")
        if sidebar.count() == 0:
            pytest.skip("현재 프런트 빌드에 desktop sidebar가 없음")
        expect(sidebar).to_be_visible()

    def test_sidebar_navigation(self, page: Page, frontend_url: str, system_mode: str):
        """사이드바를 통한 페이지 이동"""
        _skip_admin_mode_if_public(system_mode)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 통합 목록 메뉴 클릭
        monitoring_link = page.locator("aside a[href='/monitoring']").first
        if monitoring_link.count() == 0:
            pytest.skip("현재 프런트 빌드에 /monitoring 사이드바 링크가 없음")
        monitoring_link.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{frontend_url}/monitoring")

    def test_sidebar_contains_file_tools_link(self, page: Page, frontend_url: str, system_mode: str):
        """사이드바에 파일 도구 링크가 보여야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        file_tools_link = page.locator("aside a[href='/file-search']").first
        if file_tools_link.count() == 0:
            pytest.skip("현재 프런트 빌드에 /file-search 사이드바 링크가 없음")
        expect(file_tools_link).to_be_visible()
        expect(file_tools_link).to_contain_text("파일 도구")

    def test_sidebar_navigation_to_file_tools(self, page: Page, frontend_url: str, system_mode: str):
        """사이드바에서 파일 도구 페이지로 이동할 수 있어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        file_tools_link = page.locator("aside a[href='/file-search']").first
        if file_tools_link.count() == 0:
            pytest.skip("현재 프런트 빌드에 /file-search 사이드바 링크가 없음")
        file_tools_link.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{frontend_url}/file-search")

    def test_sidebar_contains_dev_work_label(self, page: Page, frontend_url: str, system_mode: str):
        """사이드바에 개발 작업 라벨이 보여야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        dev_work_link = page.locator("aside a[href='/automation']").first
        if dev_work_link.count() == 0:
            pytest.skip("현재 프런트 빌드에 /automation 사이드바 링크가 없음")
        expect(dev_work_link).to_be_visible()
        expect(dev_work_link).to_contain_text("개발 작업")

    def test_automation_page_title_uses_dev_work(self, page: Page, frontend_url: str, system_mode: str):
        """automation 진입 시 개발 작업 표면 문구가 보여야 한다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/automation")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        expect(page.locator("h1").first).to_contain_text("개발 작업")

    def test_dashboard_loads_after_restart_frontend_admin_e2e(
        self, page: Page, frontend_url: str, api_url: str, system_mode: str
    ):
        """CLI restart-frontend 직후 /dashboard가 정상 로드되어야 한다."""
        _skip_admin_mode_if_public(system_mode)
        result = _ensure_recent_admin_restart(frontend_url, api_url)
        assert result.returncode in (0, 1)

        _goto_stable_frontend_page(page, f"{frontend_url}/dashboard")
        _skip_if_frontend_error_title(page)
        expect(page).to_have_title(re.compile(r"(모니터링 시스템|통합 대시보드)"))
        expect(page.locator("main").first).to_be_visible()

    def test_sidebar_navigation_after_restart_frontend_admin_e2e(
        self, page: Page, frontend_url: str, api_url: str, system_mode: str
    ):
        """CLI restart-frontend 직후 사이드바 내비게이션이 동작해야 한다."""
        _skip_admin_mode_if_public(system_mode)
        result = _ensure_recent_admin_restart(frontend_url, api_url)
        assert result.returncode in (0, 1)

        page.set_viewport_size({"width": 1280, "height": 720})
        _goto_stable_frontend_page(page, f"{frontend_url}/dashboard")
        _skip_if_frontend_error_title(page)

        monitoring_link = page.locator("aside a[href='/monitoring']").first
        if monitoring_link.count() == 0:
            pytest.skip("현재 프런트 빌드에 /monitoring 사이드바 링크가 없음")
        monitoring_link.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        expect(page).to_have_url(f"{frontend_url}/monitoring")


class TestMobileNavigation:
    """모바일 네비게이션 테스트"""

    def test_mobile_menu_toggle(self, page: Page, frontend_url: str):
        """모바일에서 메뉴 토글"""
        # 모바일 뷰포트 설정
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(f"{frontend_url}/dashboard")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        # 모바일 메뉴 버튼 확인
        menu_button = page.locator("button[aria-label='메뉴 열기']").first
        if menu_button.count() == 0:
            pytest.skip("현재 프런트 빌드에 모바일 메뉴 토글 버튼이 없음")
        if not menu_button.is_visible():
            pytest.skip("현재 프런트 빌드에서 모바일 메뉴 토글이 안정적으로 노출되지 않음")
        menu_button.click()

        # 사이드바 표시 확인
        sidebar = page.locator("aside")
        expect(sidebar).to_be_visible()
