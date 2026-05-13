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


def _stub_dev_runner_shell(page: Page, runner_id: str, plan_file: str, recent_handler) -> None:
    gate_snapshot = {
        "state": "open",
        "reason": "test gate open",
        "since": None,
        "apiPort": 8001,
    }
    page.route("**/__local/api-gate/status", lambda route: _fulfill_json(route, gate_snapshot))
    page.route(
        "**/__local/api-gate/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"event: gate_state\ndata: {json.dumps(gate_snapshot)}\n\n",
        ),
    )
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
                "start_time": "2026-05-04T23:35:00",
                "current_cycle": 1,
                "current_plan_name": "managed catch-up",
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
                    "engine": "codex",
                    "status": "running",
                    "running": True,
                    "pid": 12345,
                    "current_cycle": 1,
                    "start_time": "2026-05-04T23:35:00",
                    "trigger": "user",
                    "visible": True,
                    "execution_count": 1,
                }
            ],
        ),
    )
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: route.fulfill(status=503, body="diagnostics down"))
    page.route(re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"), recent_handler)
    page.route(re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"), lambda route: _fulfill_json(route, {"lines": [], "total_lines": 0, "offset": 0, "has_more": False}))
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body='event: status\ndata: {"runners": []}\n\n',
        ),
    )


def test_managed_live_log_shows_recent_line_after_diagnostics_failure(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "managed-catchup-ok"
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-05-04_fix-dev-runner-managed-live-log-catchup-retry.md"

    def handle_recent(route):
        _fulfill_json(
            route,
            {
                "lines": ["[23:35:10] [RESULT] managed recent line is visible"],
                "total_lines": 1,
                "from_line": 0,
            },
        )

    _stub_dev_runner_shell(page, runner_id, plan_file, handle_recent)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")
    page.wait_for_selector("main", timeout=30000)

    expect(page.get_by_text("managed recent line is visible")).to_be_visible(timeout=30000)
    expect(page.get_by_text("로그가 없습니다")).to_have_count(0)


def test_managed_live_log_retries_recent_after_initial_failure(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "managed-catchup-retry"
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-05-04_fix-dev-runner-managed-live-log-catchup-retry.md"
    recent_calls = 0

    def handle_recent(route):
        nonlocal recent_calls
        recent_calls += 1
        if recent_calls == 1:
            route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "gate not open yet"}))
            return
        _fulfill_json(
            route,
            {
                "lines": ["[23:35:12] [RESULT] managed retry recovered recent line"],
                "total_lines": 1,
                "from_line": 0,
            },
        )

    _stub_dev_runner_shell(page, runner_id, plan_file, handle_recent)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")
    page.wait_for_selector("main", timeout=30000)

    expect(page.get_by_text("managed retry recovered recent line")).to_be_visible(timeout=30000)
    assert recent_calls >= 2
