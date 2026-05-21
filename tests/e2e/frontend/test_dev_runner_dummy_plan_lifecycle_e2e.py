import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.dev_runner.dummy_plan_lifecycle_helpers import DUMMY_PLAN_FIXTURE, DUMMY_PLAN_SENTINEL


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} - admin E2E 스킵")


def _fulfill_json(route, payload, status: int = 200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def test_dummy_plan_runner_log_and_merge_result_visible(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "dummy-plan-playwright-ui"
    hidden_noise_runner_id = "hidden-dummy-plan-noise"
    plan_file = f"tests/dev_runner/fixtures/{DUMMY_PLAN_FIXTURE}"
    route_counts = {"runners": 0, "recent": 0, "full": 0, "merge": 0}

    def runners_handler(route):
        route_counts["runners"] += 1
        _fulfill_json(
            route,
            [
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "codex",
                    "status": "stopped",
                    "running": False,
                    "pid": None,
                    "current_cycle": 1,
                    "start_time": "2026-05-21T18:20:00",
                    "trigger": "user:all",
                    "visible": True,
                    "execution_count": 1,
                    "merge_status": "merged",
                    "merge_message": "dummy temp repo merged",
                    "display_state": "merged",
                    "display_label": "머지됨",
                    "display_severity": "success",
                },
                {
                    "runner_id": hidden_noise_runner_id,
                    "plan_file": "tests/dev_runner/fixtures/hidden_dummy_plan.md",
                    "engine": "codex",
                    "status": "stopped",
                    "running": False,
                    "trigger": "tc:hidden_dummy_plan",
                    "visible": False,
                    "merge_status": "merged",
                },
            ],
        )

    def recent_handler(route):
        route_counts["recent"] += 1
        _fulfill_json(
            route,
            {
                "lines": [
                    "[INFO] dummy plan accepted",
                    f"[INFO] {DUMMY_PLAN_SENTINEL}",
                    "[MERGE] dummy temp repo merged",
                ],
                "total_lines": 3,
                "from_line": 0,
            },
        )

    def full_handler(route):
        route_counts["full"] += 1
        _fulfill_json(
            route,
            {
                "lines": [
                    "[INFO] dummy plan accepted",
                    f"[INFO] {DUMMY_PLAN_SENTINEL}",
                    "[MERGE] dummy temp repo merged",
                ],
                "total_lines": 3,
                "offset": 0,
                "has_more": False,
            },
        )

    def merge_handler(route):
        route_counts["merge"] += 1
        _fulfill_json(
            route,
            {
                "runner_id": runner_id,
                "status": "merged",
                "test_passed": None,
                "fix_attempts": 0,
                "message": "dummy temp repo merged",
                "reason": None,
                "quarantine_diff_path": None,
                "gate_evidence_summary": None,
            },
        )

    page.route("**/api/v1/dev-runner/status", lambda route: _fulfill_json(route, {"running": False, "listener_alive": True, "redis_connected": True}))
    page.route("**/api/v1/dev-runner/runners", runners_handler)
    page.route("**/api/v1/dev-runner/runners/orphans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: route.fulfill(status=503, body="diagnostics down"))
    page.route(re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"), recent_handler)
    page.route(re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"), full_handler)
    page.route(f"**/api/v1/dev-runner/merge/{runner_id}", merge_handler)
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body='event: status\ndata: {"runners": []}\n\n',
        ),
    )

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text(DUMMY_PLAN_SENTINEL)).to_be_visible(timeout=10000)
    expect(page.get_by_role("button", name=re.compile(DUMMY_PLAN_FIXTURE))).to_be_visible(timeout=10000)
    expect(page.get_by_text(re.compile("merged|머지됨|dummy temp repo merged", re.IGNORECASE)).first).to_be_visible(timeout=10000)
    expect(page.get_by_text(hidden_noise_runner_id)).to_have_count(0)
    assert route_counts["runners"] >= 1
    assert route_counts["recent"] >= 1
