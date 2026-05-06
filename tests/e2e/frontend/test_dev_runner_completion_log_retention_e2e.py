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


def test_completed_claude_runner_keeps_plan_labels_logs_and_filters(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    runner_id = "completion-retention-e2e"
    filename = "2026-05-05_fix-dev-runner-labels-logs-and-completion-state_todo-1.md"
    plan_file = rf"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\{filename}"
    long_result = "\n".join(
        [
            "claude result line 1",
            "claude result line 2",
            "claude result line 3",
            "claude result line 4 should be collapsed until expanded",
        ]
    )
    recent_lines = [
        "[15:59:01] [INFO] START | log_path=D:\\work\\project\\tools\\common\\logs\\plan-runner-stream-completion-retention-e2e.log",
        f"[15:59:02] [RESULT] {long_result}",
        "[15:59:03] [ERROR] completion hidden error example",
        "[15:59:04] [STDERR] completion hidden stderr example",
        "[15:59:05] [DONE] LLM_DONE claude-sonnet-4-6 | out:1974 in:5 | 62s",
    ]
    runner_payload = {
        "runner_id": runner_id,
        "plan_file": plan_file,
        "display_plan_name": filename,
        "engine": "claude",
        "status": "completed",
        "running": False,
        "pid": None,
        "current_cycle": None,
        "start_time": "2026-05-05T15:59:01",
        "trigger": "user",
        "visible": True,
        "execution_count": 2,
        "exit_reason": "completed",
    }

    page.route(
        "**/api/v1/dev-runner/status",
        lambda route: _fulfill_json(
            route,
            {
                "running": False,
                "listener_alive": True,
                "redis_connected": True,
                "pid": None,
                "plan_file": plan_file,
                "start_time": "2026-05-05T15:59:01",
                "current_cycle": None,
                "exit_code": 0,
                "crashed": False,
                "current_plan_name": filename,
                "runner_id": runner_id,
            },
        ),
    )
    page.route(
        "**/api/v1/dev-runner/runners",
        lambda route: _fulfill_json(
            route,
            [runner_payload],
        ),
    )
    page.route("**/api/v1/dev-runner/tasks/current-tracking", lambda route: _fulfill_json(route, None))
    page.route(
        "**/api/v1/dev-runner/plans",
        lambda route: _fulfill_json(
            route,
            [
                {
                    "path": plan_file,
                    "filename": filename,
                    "status": "구현중",
                    "summary": "Dev Runner UI labels, logs, and completed state",
                    "progress": {"done": 120, "total": 132},
                    "path_type": "file",
                }
            ],
        ),
    )
    page.route("**/api/v1/dev-runner/logs/diagnostics", lambda route: _fulfill_json(route, {"steps": []}))
    page.route(
        re.compile(r".*/api/v1/dev-runner/logs/recent(?:\?.*)?$"),
        lambda route: _fulfill_json(route, {"lines": recent_lines, "total_lines": len(recent_lines), "from_line": 0}),
    )
    page.route(
        re.compile(r".*/api/v1/dev-runner/logs/full(?:\?.*)?$"),
        lambda route: _fulfill_json(
            route,
            {"lines": recent_lines, "total_lines": len(recent_lines), "offset": 0, "has_more": False},
        ),
    )
    page.route(
        "**/api/v1/dev-runner/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"event: status\ndata: {json.dumps({'runners': [runner_payload]})}\n\n",
        ),
    )

    page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")

    expect(page.get_by_text(filename).first).to_be_visible()
    expect(page.get_by_text("Runner 1")).to_have_count(0)
    expect(page.get_by_text("120/132 (91%)")).to_be_visible()

    expect(page.get_by_text("claude result line 1")).to_be_visible()
    expect(page.get_by_text("claude result line 4 should be collapsed until expanded")).to_have_count(0)
    page.get_by_role("button", name=re.compile(r"더보기.*\+1 lines")).click()
    expect(page.get_by_text("claude result line 4 should be collapsed until expanded")).to_be_visible()

    expect(page.get_by_text("completion hidden error example")).to_be_visible()
    expect(page.get_by_text("completion hidden stderr example")).to_be_visible()
    page.get_by_role("button", name="ERROR").click()
    page.get_by_role("button", name="STDERR").click()
    expect(page.get_by_text("completion hidden error example")).to_have_count(0)
    expect(page.get_by_text("completion hidden stderr example")).to_have_count(0)
    expect(page.get_by_text("hidden 2")).to_be_visible()
    page.get_by_role("button", name="ERROR").click()
    expect(page.get_by_text("completion hidden error example")).to_be_visible()

    expect(page.get_by_text("LLM_DONE claude-sonnet-4-6")).to_be_visible()
    page.get_by_title("편집 모드").click()
    expect(page.get_by_title("무시").first).to_be_visible()
    expect(page.get_by_title("등록 해제").first).to_be_visible()
