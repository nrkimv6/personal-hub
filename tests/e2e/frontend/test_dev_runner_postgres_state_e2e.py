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


def _stub_dev_runner_shell(page: Page, runner_id: str) -> None:
    plan_file = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\postgres-state-e2e.md"

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
    page.route("**/api/v1/dev-runner/runners/orphans", lambda route: _fulfill_json(route, []))
    page.route(
        "**/api/v1/dev-runner/runners",
        lambda route: _fulfill_json(
            route,
            [
                {
                    "runner_id": runner_id,
                    "plan_file": plan_file,
                    "engine": "codex",
                    "status": "completed",
                    "running": False,
                    "pid": None,
                    "start_time": "2026-05-06T10:30:00",
                    "trigger": "user",
                    "visible": True,
                    "execution_count": 1,
                    "branch": "impl/postgres-state-e2e",
                    "worktree_path": "D:/work/project/tools/monitor-page/.worktrees/impl-postgres-state-e2e",
                    "redis_missing": True,
                    "log_file_found": True,
                    "display_state": "stopped",
                    "display_label": "중지됨",
                }
            ],
        ),
    )
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route("**/api/v1/dev-runner/plans", lambda route: _fulfill_json(route, []))
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: _fulfill_json(route, {"steps": []}))
    page.route("**/api/v1/dev-runner/workflows*", lambda route: _fulfill_json(route, []))
    page.route(
        "**/api/v1/dev-runner/merge-queue",
        lambda route: _fulfill_json(
            route,
            [
                {
                    "runner_id": "postgres-merge-e2e",
                    "branch": "impl/postgres-state-e2e",
                    "plan_file": plan_file,
                    "project": "monitor-page",
                    "status": "queued",
                    "timestamp": "2026-05-06T10:31:00",
                    "worktree_path": "D:/work/project/tools/monitor-page/.worktrees/impl-postgres-state-e2e",
                }
            ],
        ),
    )
    page.route(
        re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"),
        lambda route: _fulfill_json(
            route,
            {
                "lines": ["[10:30:01] [INFO] postgres state log restored from DB row"],
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


def test_db_only_runner_row_stays_visible_with_redis_missing_fixture(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "postgres-state-e2e"
    _stub_dev_runner_shell(page, runner_id)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text("로그 복구")).to_be_visible(timeout=10000)
    expect(page.get_by_text("postgres state log restored from DB row")).to_be_visible(timeout=10000)


def test_merge_queue_panel_renders_db_pending_row_with_stable_key(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "postgres-state-e2e"
    _stub_dev_runner_shell(page, runner_id)

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")
    page.get_by_role("button", name=re.compile(r"^Merge")).click()

    expect(page.get_by_text("postgres-merge-e2e")).to_be_visible(timeout=10000)
    expect(page.get_by_text("queued")).to_be_visible(timeout=5000)
