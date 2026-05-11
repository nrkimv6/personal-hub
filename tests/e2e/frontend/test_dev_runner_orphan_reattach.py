import json
import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"currently system mode={system_mode} - admin E2E only")


def _fulfill_json(route, payload, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _stub_dev_runner_shell(page: Page, runner_id: str) -> dict[str, bool]:
    state = {"reattached": False}
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\orphan-reattach-e2e.md"

    def handle_status(route):
        _fulfill_json(
            route,
            {
                "running": state["reattached"],
                "listener_alive": True,
                "redis_connected": True,
                "pid": 4412 if state["reattached"] else None,
                "plan_file": plan_file if state["reattached"] else None,
                "start_time": "2026-05-05T23:00:00" if state["reattached"] else None,
                "current_cycle": 1 if state["reattached"] else None,
                "current_plan_name": "orphan reattach e2e",
                "runner_id": runner_id if state["reattached"] else None,
            },
        )

    def handle_runners(route):
        runners = []
        if state["reattached"]:
            runners.append(
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "claude",
                    "status": "running",
                    "running": True,
                    "pid": 4412,
                    "start_time": "2026-05-05T23:00:00",
                    "trigger": "user",
                    "visible": True,
                    "execution_count": 1,
                }
            )
        _fulfill_json(route, runners)

    def handle_orphans(route):
        if state["reattached"]:
            _fulfill_json(route, [])
            return
        _fulfill_json(
            route,
            [
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "claude",
                    "trigger": "user",
                    "pid": 4412,
                    "pid_kind": "parent",
                    "log_file": "logs/plan-runner-stream-orphan-reattach-e2e.log",
                    "log_mtime": "2026-05-05T23:00:00",
                    "confidence": "high",
                    "reattach_mode": "full",
                    "can_reattach": True,
                    "can_force_kill": True,
                    "warnings": [],
                }
            ],
        )

    def handle_reattach(route):
        state["reattached"] = True
        _fulfill_json(
            route,
            {
                "success": True,
                "runner_id": runner_id,
                "message": "reattached",
                "reattach_mode": "full",
                "candidate": {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "claude",
                    "confidence": "high",
                    "reattach_mode": "full",
                    "can_reattach": True,
                    "can_force_kill": True,
                    "warnings": [],
                },
            },
        )

    page.route("**/api/v1/dev-runner/status", handle_status)
    page.route("**/api/v1/dev-runner/runners/orphans", handle_orphans)
    page.route(re.compile(r".*/api/v1/dev-runner/runners/.*/reattach$"), handle_reattach)
    page.route("**/api/v1/dev-runner/runners", handle_runners)
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: _fulfill_json(route, {"steps": []}))
    page.route("**/api/v1/dev-runner/workflows*", lambda route: _fulfill_json(route, []))
    page.route(
        re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"),
        lambda route: _fulfill_json(
            route,
            {
                "lines": ["[23:00:01] [INFO] reattached runner log is visible"],
                "total_lines": 1,
                "from_line": 0,
            },
        ),
    )
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
    return state


def test_orphan_candidate_row_is_visible(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "orphan-reattach-e2e"
    _stub_dev_runner_shell(page, runner_id)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("Redis 상태 소실")).to_be_visible(timeout=10000)
    expect(page.locator("button", has_text="재연결").first).to_be_visible(timeout=5000)
    expect(page.locator("button", has_text="강제 종료").first).to_be_visible(timeout=5000)


def test_reattach_click_restores_runner_and_log(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "orphan-reattach-e2e"
    _stub_dev_runner_shell(page, runner_id)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")
    page.locator("button", has_text="재연결").first.click()

    expect(page.get_by_text("reattached runner log is visible")).to_be_visible(timeout=10000)
    expect(page.get_by_text("Redis 상태 소실")).to_have_count(0)
