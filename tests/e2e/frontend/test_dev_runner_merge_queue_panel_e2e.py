import json
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _fulfill_json(route, payload, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _stub_dev_runner_shell(page: Page) -> None:
    page.route(
        "**/api/v1/dev-runner/status",
        lambda route: _fulfill_json(
            route,
            {
                "running": False,
                "listener_alive": True,
                "redis_connected": True,
                "pid": None,
                "plan_file": None,
                "runner_id": None,
            },
        ),
    )
    page.route("**/api/v1/dev-runner/runners", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: route.fulfill(status=503, body="diagnostics down"))
    page.route("**/api/v1/dev-runner/workflows*", lambda route: _fulfill_json(route, []))
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body='event: status\ndata: {"runners": []}\n\n',
        ),
    )


def _duplicate_merge_queue_rows():
    return [
        {
            "runner_id": "duplicate-runner",
            "branch": "impl/first",
            "plan_file": "docs/plan/first.md",
            "project": "monitor-page",
            "status": "done",
            "timestamp": "2026-05-11T10:00:01",
            "worktree_path": "",
        },
        {
            "runner_id": "duplicate-runner",
            "branch": "impl/second",
            "plan_file": "docs/plan/second.md",
            "project": "monitor-page",
            "status": "done",
            "timestamp": "2026-05-11T10:00:02",
            "worktree_path": "",
        },
    ]


def test_merge_queue_tab_handles_duplicate_runner_ids_without_console_error(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    if system_mode != "admin":
        pytest.skip(f"currently system mode={system_mode} - admin E2E only")

    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    _stub_dev_runner_shell(page)
    page.route("**/api/v1/dev-runner/merge-queue", lambda route: _fulfill_json(route, _duplicate_merge_queue_rows()))

    page.goto(f"{frontend_url}/automation?runner=1bead8e6")
    page.get_by_role("button", name=re.compile(r"^Merge")).click()

    expect(page.get_by_text("Completed")).to_be_visible(timeout=10000)
    expect(page.get_by_text("impl/first")).to_be_visible(timeout=5000)
    expect(page.get_by_text("impl/second")).to_be_visible(timeout=5000)
    assert not any("each_key_duplicate" in error for error in console_errors)


def test_merge_queue_refresh_button_recovers_after_duplicate_runner_response(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    if system_mode != "admin":
        pytest.skip(f"currently system mode={system_mode} - admin E2E only")

    _stub_dev_runner_shell(page)
    page.route("**/api/v1/dev-runner/merge-queue", lambda route: _fulfill_json(route, _duplicate_merge_queue_rows()))

    page.goto(f"{frontend_url}/automation?runner=1bead8e6")
    page.get_by_role("button", name=re.compile(r"^Merge")).click()

    refresh = page.locator('button[title="Refresh"]').first
    expect(refresh).to_be_enabled(timeout=10000)
    refresh.click()
    expect(refresh).to_be_enabled(timeout=10000)
