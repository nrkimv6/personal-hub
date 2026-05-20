"""
T4: Active LogViewer catch-up rendering E2E tests.

Covers:
- Header-only response (TRIGGER/RUN_META/ENV/START) should not prevent catch-up retry
- [PR:...] and [PS:...] prefix lines with same body render identically
- Non-error log content renders even when ERROR/STDERR filter is hidden
"""
import json
import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} - admin E2E 스킵")


def _fulfill_json(route, payload, status: int = 200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _stub_active_runner(page: Page, runner_id: str, recent_handler, full_handler=None) -> None:
    """Stub all dev-runner API routes for an active runner."""
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-05-05_fix-dev-runner-active-logviewer-catchup-rendering.md"

    page.route(
        "**/api/v1/dev-runner/status",
        lambda route: _fulfill_json(
            route,
            {
                "running": True,
                "listener_alive": True,
                "redis_connected": True,
                "pid": 12345,
                "plan_file": plan_file,
                "start_time": "2026-05-05T10:00:00",
                "current_cycle": 1,
                "current_plan_name": "active logviewer fix",
                "runner_id": runner_id,
            },
        ),
    )
    page.route(
        "**/api/v1/dev-runner/runners",
        lambda route: _fulfill_json(
            route,
            [
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "claude",
                    "status": "running",
                    "running": True,
                    "pid": 12345,
                    "current_cycle": 1,
                    "start_time": "2026-05-05T10:00:00",
                    "trigger": "user",
                    "visible": True,
                    "execution_count": 1,
                }
            ],
        ),
    )
    page.route("**/api/v1/dev-runner/runners/orphans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: route.fulfill(status=503, body="diagnostics down"))
    page.route(re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"), recent_handler)
    if full_handler:
        page.route(re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"), full_handler)
    else:
        page.route(
            re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"),
            lambda route: _fulfill_json(route, {"lines": [], "total_lines": 0, "offset": 0, "has_more": False}),
        )
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body='event: status\ndata: {"runners": []}\n\n',
        ),
    )


def test_active_logviewer_shows_stream_content_not_header_only(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    """
    TRIGGER/RUN_META/ENV header lines must not prevent catch-up.
    When /logs/recent returns actual [INFO]/[THINK]/[TOOL] lines,
    UI must display them rather than staying at 로그가 없습니다.
    """
    _skip_admin_mode_if_public(system_mode)

    runner_id = "active-logviewer-stream"

    def handle_recent(route):
        _fulfill_json(
            route,
            {
                "lines": [
                    "[PR:a9694a1d] [10:00:01] [TRIGGER] user request",
                    "[PR:a9694a1d] [10:00:02] [RUN_META] plan=fix-rendering",
                    "[PR:a9694a1d] [10:00:03] [ENV] MODE=admin",
                    "[PR:a9694a1d] [10:00:04] [START] execution started",
                    "[PR:a9694a1d] [10:00:05] [INFO] stream content is now visible",
                    "[PR:a9694a1d] [10:00:06] [THINK] analyzing the problem",
                ],
                "total_lines": 6,
                "from_line": 0,
            },
        )

    _stub_active_runner(page, runner_id, handle_recent)
    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("stream content is now visible")).to_be_visible(timeout=10000)
    expect(page.get_by_text("analyzing the problem")).to_be_visible(timeout=5000)
    expect(page.get_by_text("로그가 없습니다")).to_have_count(0)


def test_ps_prefix_line_renders_same_as_pr_prefix(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    """
    [PR:...] and [PS:...] prefix lines with identical body must render
    the same tag and message content — [PS:...] should not be ignored or
    shown as raw text.
    """
    _skip_admin_mode_if_public(system_mode)

    runner_id = "active-logviewer-ps-prefix"

    def handle_recent(route):
        _fulfill_json(
            route,
            {
                "lines": [
                    "[PR:a9694a1d] [10:01:00] [INFO] pr prefix line",
                    "[PS:a9694a1d] [10:01:01] [THINK] ps prefix reasoning here",
                    "[PS:a9694a1d] [10:01:02] [TOOL] ps prefix tool call result",
                ],
                "total_lines": 3,
                "from_line": 0,
            },
        )

    _stub_active_runner(page, runner_id, handle_recent)
    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("pr prefix line")).to_be_visible(timeout=10000)
    expect(page.get_by_text("ps prefix reasoning here")).to_be_visible(timeout=5000)
    expect(page.get_by_text("ps prefix tool call result")).to_be_visible(timeout=5000)
    # None of them should appear as raw [PS:...] text
    expect(page.get_by_text(re.compile(r"\[PS:a9694a1d\]"))).to_have_count(0)


def test_copy_log_includes_full_log_not_header_only(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    """
    copyLog() must use /logs/full API and include all lines.
    Regression: #3→#4 approval_required/service_lock WARN lines were silently
    dropped by isStale filter + lines-state limitation.
    """
    _skip_admin_mode_if_public(system_mode)

    page.context.grant_permissions(["clipboard-read", "clipboard-write"])

    runner_id = "copy-log-full-state-test"

    def handle_recent(route):
        _fulfill_json(
            route,
            {
                "lines": [
                    "[PR:a9694a1d] [10:00:01] [TRIGGER] user request",
                    "[PR:a9694a1d] [10:00:02] [RUN_META] plan=copy-test",
                    "[PR:a9694a1d] [10:00:03] [START] execution started",
                    "[PR:a9694a1d] [10:00:04] [INFO] some content line",
                ],
                "total_lines": 4,
                "from_line": 0,
            },
        )

    def handle_full(route):
        _fulfill_json(
            route,
            {
                "lines": [
                    "[PR:a9694a1d] [10:00:01] [TRIGGER] user request",
                    "[PR:a9694a1d] [10:00:02] [RUN_META] plan=copy-test",
                    "[PR:a9694a1d] [10:00:03] [START] execution started",
                    "[PR:a9694a1d] [10:00:04] [INFO] some content line",
                    "[PR:a9694a1d] [10:00:05] [WARN] MERGE_PRECHECK_FAILED[service_lock] deployment blocked",
                ],
                "total_lines": 5,
                "offset": 0,
                "has_more": False,
            },
        )

    _stub_active_runner(page, runner_id, handle_recent, full_handler=handle_full)
    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("some content line")).to_be_visible(timeout=10000)

    copy_btn = page.get_by_title("로그 복사 (full log + 머지 상태)")
    expect(copy_btn).to_be_visible(timeout=5000)
    copy_btn.click()

    expect(page.get_by_title("복사됨")).to_be_visible(timeout=5000)

    clipboard_text = page.evaluate("navigator.clipboard.readText()")

    assert "MERGE_PRECHECK_FAILED[service_lock]" in clipboard_text, (
        f"Expected MERGE_PRECHECK_FAILED[service_lock] in clipboard, got: {clipboard_text[:300]}"
    )


def test_non_error_content_visible_with_error_filter_hidden(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    """
    When ERROR/STDERR filter is toggled off, non-error log content
    (INFO, THINK, TOOL) must still be visible in the LogViewer.
    """
    _skip_admin_mode_if_public(system_mode)

    runner_id = "active-logviewer-filter"

    def handle_recent(route):
        _fulfill_json(
            route,
            {
                "lines": [
                    "[PR:a9694a1d] [10:02:00] [ERROR] this is an error line",
                    "[PR:a9694a1d] [10:02:01] [INFO] this info line must remain visible",
                    "[PR:a9694a1d] [10:02:02] [TOOL] tool output always visible",
                ],
                "total_lines": 3,
                "from_line": 0,
            },
        )

    _stub_active_runner(page, runner_id, handle_recent)
    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    # Wait for logs to appear first
    expect(page.get_by_text("this info line must remain visible")).to_be_visible(timeout=10000)

    # Toggle ERROR filter off if available — look for ERROR filter button
    error_filter = page.locator("button", has_text="ERROR").first
    if error_filter.is_visible():
        error_filter.click()

    # Non-error content must still be visible after filter toggle
    expect(page.get_by_text("this info line must remain visible")).to_be_visible(timeout=5000)
    expect(page.get_by_text("tool output always visible")).to_be_visible(timeout=5000)
