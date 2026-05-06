"""
E2E 테스트용 Playwright 픽스처

프론트엔드 UI 테스트를 위한 브라우저/페이지 픽스처를 제공합니다.
"""

import sys
import os
import time

# Windows UTF-8 설정
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

import json
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, expect
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 테스트 설정
E2E_CONFIG = {
    "api_url": os.environ.get("E2E_API_URL", "http://localhost:8001"),
    "frontend_url": os.environ.get("E2E_FRONTEND_URL", "http://localhost:6101"),
    # public PREVIEW의 기본 host/port는 frontend route-mode helper의 public 계약과 동일하게 유지한다.
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
        service_workers="block",
        extra_http_headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
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
    _wait_for_frontend_available(url, companion_api_url=E2E_CONFIG["api_url"])
    return url


@pytest.fixture
def public_frontend_url():
    """공개 프론트엔드 URL"""
    url = E2E_CONFIG["public_frontend_url"]
    _wait_for_frontend_available(url)
    return url


@pytest.fixture
def system_mode(api_url: str) -> str:
    """현재 API 모드(public/admin)."""
    mode_url = f"{api_url}/api/v1/system/mode"
    payload = _load_json_with_retry(mode_url)
    return str(payload.get("mode") or "public")


# =============================================================================
# 헬퍼 함수
# =============================================================================

def wait_for_app_ready(page: Page, url: str, timeout: int = 30000):
    """
    앱이 준비될 때까지 대기

    SvelteKit 앱 shell과 hydration marker가 준비될 때까지 기다립니다.
    Background polling can keep network activity open after the product surface is usable.
    """
    page.goto(url, wait_until="domcontentloaded")
    expect(page.locator("main").first).to_be_visible(timeout=timeout)
    # SvelteKit hydration 완료 대기
    page.wait_for_selector("[data-sveltekit-hydrated]", timeout=timeout, state="attached")


def _wait_for_http_available(url: str, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: Exception | None = None

    while time.time() <= deadline:
        try:
            with urlopen(url, timeout=5):
                return
        except HTTPError:
            return
        except (URLError, OSError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1.0)

    pytest.fail(f"HTTP endpoint not available: {url} ({last_error})")


def _assert_frontend_available(url: str) -> None:
    """One-shot healthcheck for tests that validate urlopen timeout behavior.

    NOTE: Keep this as a single attempt (no retry loop) so unit/integration tests stay fast and deterministic.
    """
    try:
        with urlopen(url, timeout=5):
            return
    except HTTPError:
        return
    except (URLError, OSError, TimeoutError) as exc:
        pytest.fail(f"HTTP endpoint not available: {url} ({exc})")


def _wait_for_frontend_available(url: str, companion_api_url: str | None = None) -> None:
    _wait_for_http_available(url)
    if companion_api_url:
        _wait_for_http_available(f"{companion_api_url}/api/v1/system/liveness")


def _load_json_with_retry(url: str, timeout_seconds: float = 60.0) -> dict:
    deadline = time.time() + max(timeout_seconds, 1.0)
    last_error: Exception | None = None

    while time.time() <= deadline:
        try:
            with urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            pytest.fail(f"system/mode endpoint returned HTTP {exc.code}: {url}")
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.0)

    pytest.fail(f"system/mode endpoint unavailable: {url} ({last_error})")


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
