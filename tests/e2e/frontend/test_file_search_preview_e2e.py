import json
import pytest
from playwright.sync_api import BrowserContext, Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _stub_file_search_bootstrap(page: Page) -> None:
    page.route(
        "**/api/v1/file-search/presets",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    page.route(
        "**/api/v1/file-search/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "everything_ok": True,
                    "everything_message": "",
                    "ripgrep_ok": True,
                    "ripgrep_path": "rg",
                }
            ),
        ),
    )
    page.route(
        "**/api/v1/file-search/ignore-patterns",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    # File search page loads these on mount (SearchHistoryBar)
    page.route(
        "**/api/v1/file-search/history*",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )
    page.route(
        "**/api/v1/file-search/suggestions*",
        lambda route: route.fulfill(status=200, content_type="application/json", body="[]"),
    )


def test_file_search_filename_preview_toggle_and_copy_path(
    page: Page,
    context: BrowserContext,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _stub_file_search_bootstrap(page)

    search_id = "test-search-id"
    results_payload = {
        "results": [
            {
                "file_path": r"D:\work\project\README.md",
                "file_name": "README.md",
                "file_size": 512,
                "modified": None,
                "matches": [],
                "match_source": "filename",
            },
            {
                "file_path": r"D:\work\project\tools\monitor-page\app\main.py",
                "file_name": "main.py",
                "file_size": 1024,
                "modified": None,
                "matches": [
                    {
                        "line_number": 10,
                        "line_text": "def hello():",
                        "context_before": [],
                        "context_after": [],
                        "submatches": [],
                    }
                ],
                "match_source": "content",
            },
        ],
        "total_count": 2,
        "search_time_ms": 123,
        "mode": "both",
        "truncated": False,
    }

    page.route(
        "**/api/v1/file-search/search",
        lambda route: route.fulfill(
            status=202,
            content_type="application/json",
            body=json.dumps({"search_id": search_id, "status": "queued"}),
        ),
    )
    page.route(
        f"**/api/v1/file-search/search/{search_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "search_id": search_id,
                    "status": "completed",
                    "result": results_payload,
                    "error_message": None,
                }
            ),
        ),
    )
    page.route(
        "**/api/v1/file-search/preview?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "file_path": r"D:\work\project\README.md",
                    "file_name": "README.md",
                    "extension": "md",
                    "size_bytes": 42,
                    "encoding": "utf-8",
                    "content": "# Hello\n",
                }
            ),
        ),
    )

    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)

    page.goto(f"{frontend_url}/file-search")
    page.wait_for_load_state("networkidle")

    page.get_by_placeholder("파일명 또는 내용 검색... (Ctrl+Enter)").fill("hello")
    page.get_by_role("button", name="검색", exact=True).click()

    expect(page.get_by_text("README.md", exact=True)).to_be_visible()

    page.get_by_text("README.md", exact=True).click()
    expect(page.get_by_role("heading", name="Hello")).to_be_visible()
    # typography 통일 후 MarkdownContent wrapper가 prose class를 가져야 한다
    expect(page.locator(".prose")).to_be_visible()

    page.get_by_role("button", name="전체보기").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading", name="Hello")).to_be_visible()

    dialog.get_by_role("button", name="Raw 보기").click()
    expect(dialog.get_by_text("# Hello")).to_be_visible()

    dialog.get_by_role("button", name="닫기").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_text("# Hello")).to_be_visible()

    # Raw/Markdown toggle state is shared between inline preview and full view.
    page.get_by_role("button", name="Markdown 보기").click()
    expect(page.get_by_role("heading", name="Hello")).to_be_visible()
    expect(page.get_by_text("# Hello")).to_have_count(0)

    page.get_by_title("full path 복사").first.click()
    assert page.evaluate("() => navigator.clipboard.readText()") == r"D:\work\project\README.md"

    page.get_by_text("README.md", exact=True).click()
    expect(page.get_by_role("heading", name="Hello")).to_have_count(0)


def test_file_search_content_match_click_still_calls_open_endpoint(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _stub_file_search_bootstrap(page)

    search_id = "test-search-id"
    results_payload = {
        "results": [
            {
                "file_path": r"D:\work\project\tools\monitor-page\app\main.py",
                "file_name": "main.py",
                "file_size": 1024,
                "modified": None,
                "matches": [
                    {
                        "line_number": 10,
                        "line_text": "def hello():",
                        "context_before": [],
                        "context_after": [],
                        "submatches": [],
                    }
                ],
                "match_source": "content",
            }
        ],
        "total_count": 1,
        "search_time_ms": 123,
        "mode": "content",
        "truncated": False,
    }

    page.route(
        "**/api/v1/file-search/search",
        lambda route: route.fulfill(
            status=202,
            content_type="application/json",
            body=json.dumps({"search_id": search_id, "status": "queued"}),
        ),
    )
    page.route(
        f"**/api/v1/file-search/search/{search_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "search_id": search_id,
                    "status": "completed",
                    "result": results_payload,
                    "error_message": None,
                }
            ),
        ),
    )

    open_calls: list[dict] = []

    def _handle_open(route):
        open_calls.append(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

    page.route("**/api/v1/file-search/open", _handle_open)

    page.goto(f"{frontend_url}/file-search")
    page.wait_for_load_state("networkidle")

    page.get_by_placeholder("파일명 또는 내용 검색... (Ctrl+Enter)").fill("hello")
    page.get_by_role("button", name="검색", exact=True).click()

    expect(page.get_by_text("main.py", exact=True)).to_be_visible()
    page.get_by_text("def hello():").click()

    assert len(open_calls) == 1
    assert open_calls[0]["file_path"].endswith("main.py")
    assert open_calls[0]["line_number"] == 10
