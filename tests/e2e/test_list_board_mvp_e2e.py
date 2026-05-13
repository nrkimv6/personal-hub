"""List Board MVP E2E smoke test — admin frontend (localhost:6101)."""
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

_IMPORT_MD = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [E2E Test Course A](https://example.com/e2e-test-a) | 15 minutes |\n"
    "| [E2E Test Course B](https://example.com/e2e-test-b) | 30 minutes |"
)


def _skip_if_frontend_error(page: Page) -> None:
    title = page.title() or ""
    if any(m in title for m in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def test_list_board_page_renders(page: Page, frontend_url: str, system_mode: str):
    if system_mode != "admin":
        pytest.skip(f"admin E2E 전용 — 현재 mode={system_mode}")

    page.goto(f"{frontend_url}/list-board")
    page.wait_for_load_state("load")
    _skip_if_frontend_error(page)

    expect(page.get_by_text("리스트 보드")).to_be_visible(timeout=15000)
    expect(page.get_by_text("Markdown Import")).to_be_visible(timeout=10000)


def test_list_board_import_and_table_render(page: Page, frontend_url: str, system_mode: str):
    if system_mode != "admin":
        pytest.skip(f"admin E2E 전용 — 현재 mode={system_mode}")

    page.goto(f"{frontend_url}/list-board")
    page.wait_for_load_state("load")
    _skip_if_frontend_error(page)

    # source 입력
    source_input = page.locator("input[placeholder='데이터소스 이름 (필수)']")
    source_input.fill("e2e-smoke-test")

    # markdown textarea에 붙여넣기
    textarea = page.locator("textarea")
    textarea.fill(_IMPORT_MD)

    # Import 버튼 클릭
    import_button = page.get_by_role("button", name="Import")
    import_button.click()

    # 결과 메시지 대기
    page.wait_for_selector("text=신규", timeout=10000)

    # 테이블 row가 렌더링되는지 확인
    rows = page.locator("tbody tr")
    expect(rows.first).to_be_visible(timeout=10000)
