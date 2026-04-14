"""
E2E 테스트용 Playwright 픽스처

프론트엔드 UI 테스트를 위한 브라우저/페이지 픽스처를 제공합니다.
"""

import sys
import os

# Windows UTF-8 설정
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

import json
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 테스트 설정
E2E_CONFIG = {
    "api_url": os.environ.get("E2E_API_URL", "http://localhost:8001"),
    "frontend_url": os.environ.get("E2E_FRONTEND_URL", "http://localhost:6101"),
    "public_frontend_url": os.environ.get("E2E_PUBLIC_FRONTEND_URL", "http://localhost:6100"),
    "headless": True,  # CI에서는 True, 디버깅 시 False
    "slow_mo": 0,  # 디버깅 시 100~500 설정
    "timeout": 30000,  # 30초
}


@pytest.fixture(scope="session")
def browser():
    """
    세션 범위 브라우저 인스턴스

    모든 E2E 테스트에서 공유되는 브라우저입니다.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=E2E_CONFIG["headless"],
            slow_mo=E2E_CONFIG["slow_mo"],
        )
        yield browser
        browser.close()


@pytest.fixture(scope="function")
def context(browser: Browser):
    """
    함수 범위 브라우저 컨텍스트

    각 테스트마다 새로운 컨텍스트를 생성하여 격리를 보장합니다.
    쿠키, 로컬스토리지 등이 테스트 간 공유되지 않습니다.
    """
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="ko-KR",
    )
    context.set_default_timeout(E2E_CONFIG["timeout"])
    yield context
    context.close()


@pytest.fixture(scope="function")
def page(context: BrowserContext):
    """
    함수 범위 페이지 인스턴스

    각 테스트마다 새로운 페이지를 제공합니다.
    """
    page = context.new_page()
    yield page
    page.close()


@pytest.fixture
def api_url():
    """API 서버 URL"""
    return E2E_CONFIG["api_url"]


@pytest.fixture
def frontend_url():
    """프론트엔드 URL"""
    url = E2E_CONFIG["frontend_url"]
    _assert_frontend_available(url)
    return url


@pytest.fixture
def public_frontend_url():
    """공개 프론트엔드 URL"""
    url = E2E_CONFIG["public_frontend_url"]
    _assert_frontend_available(url)
    return url


@pytest.fixture
def system_mode(api_url: str) -> str:
    """현재 API 모드(public/admin)."""
    mode_url = f"{api_url}/api/v1/system/mode"
    try:
        with urlopen(mode_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        pytest.fail(f"system/mode endpoint returned HTTP {exc.code}: {mode_url}")
    except (URLError, OSError, json.JSONDecodeError) as exc:
        pytest.fail(f"system/mode endpoint unavailable: {mode_url} ({exc})")
    return str(payload.get("mode") or "public")


# =============================================================================
# 헬퍼 함수
# =============================================================================

def wait_for_app_ready(page: Page, url: str, timeout: int = 30000):
    """
    앱이 준비될 때까지 대기

    SvelteKit 앱이 완전히 로드되고 JS가 실행될 때까지 기다립니다.
    """
    page.goto(url)
    page.wait_for_load_state("networkidle")
    # SvelteKit hydration 완료 대기
    page.wait_for_selector("[data-sveltekit-hydrated]", timeout=timeout, state="attached")


def _assert_frontend_available(url: str) -> None:
    try:
        # HTTPError(4xx/5xx)는 서버 기동 상태로 간주하고 테스트 진행
        with urlopen(url, timeout=2):
            pass
    except HTTPError:
        pass
    except (URLError, OSError):
        pytest.fail(f"Frontend not available: {url}")


def take_screenshot_on_failure(page: Page, request: pytest.FixtureRequest):
    """
    테스트 실패 시 스크린샷 저장

    사용법:
        @pytest.fixture(autouse=True)
        def auto_screenshot(page, request):
            yield
            if request.node.rep_call.failed:
                take_screenshot_on_failure(page, request)
    """
    screenshots_dir = PROJECT_ROOT / "tests" / "e2e" / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    test_name = request.node.name.replace("/", "_").replace(":", "_")
    screenshot_path = screenshots_dir / f"{test_name}.png"
    page.screenshot(path=str(screenshot_path))
    print(f"Screenshot saved: {screenshot_path}")
