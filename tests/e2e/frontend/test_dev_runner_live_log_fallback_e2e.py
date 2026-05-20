import json
import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} - admin E2E 스킵")


def test_dev_runner_live_log_falls_back_from_start_only_recent_to_full(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "e2e-live-log-fallback"
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-05-04_fix-dev-runner-live-log-empty-and-logs-ps1-alias.md"
    full_calls = 0

    def fulfill_json(route, payload):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    gate_snapshot = {
        "state": "open",
        "reason": "test gate open",
        "since": None,
        "apiPort": 8001,
    }

    def handle_status(route):
        fulfill_json(
            route,
            {
                "running": False,
                "listener_alive": True,
                "redis_connected": True,
                "pid": None,
                "plan_file": plan_file,
                "start_time": "2026-05-04T16:48:03",
                "current_cycle": None,
                "exit_code": 1,
                "crashed": False,
                "current_plan_name": "live log fallback",
                "runner_id": runner_id,
            },
        )

    def handle_runners(route):
        fulfill_json(
            route,
            [
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "claude",
                    "status": "completed",
                    "pid": None,
                    "current_cycle": None,
                    "start_time": "2026-05-04T16:48:03",
                    "trigger": "user",
                    "visible": True,
                    "execution_count": 2,
                }
            ],
        )

    def handle_recent(route):
        fulfill_json(
            route,
            {
                "lines": ["[plan:e2e start]"],
                "total_lines": 1,
                "from_line": 0,
            },
        )

    def handle_full(route):
        nonlocal full_calls
        full_calls += 1
        fulfill_json(
            route,
            {
                "lines": [
                    "[16:48:15] [ERROR] pre-write scope gate failed",
                    "[16:48:17] [ERROR] WRITE_SCOPE_REROUTE_REQUIRED:target_path=docs/plan/other.md",
                ],
                "total_lines": 2,
                "offset": 0,
                "has_more": False,
            },
        )

    page.route("**/__local/api-gate/status", lambda route: fulfill_json(route, gate_snapshot))
    page.route(
        "**/__local/api-gate/stream",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"event: gate_state\ndata: {json.dumps(gate_snapshot)}\n\n",
        ),
    )
    page.route("**/api/v1/dev-runner/status", handle_status)
    page.route("**/api/v1/dev-runner/runners", handle_runners)
    page.route("**/api/v1/dev-runner/runners/orphans", lambda route: fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: fulfill_json(route, {"steps": []}))
    page.route(re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"), handle_recent)
    page.route(re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"), handle_full)
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body="event: status\ndata: {\"runners\": []}\n\n",
        ),
    )

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("WRITE_SCOPE_REROUTE_REQUIRED")).to_be_visible()
    expect(page.get_by_text("[plan:e2e start]")).to_have_count(0)
    assert full_calls >= 1
