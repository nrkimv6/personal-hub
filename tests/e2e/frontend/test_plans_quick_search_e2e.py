import json
import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def test_plans_quick_search_click_focuses_plan_viewer(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)

    search_id = "test-plan-quick-search-id"
    plan_path = r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan\2026-04-25_feat-file-search-history-md-viewer-and-plan-quick-search.md"
    plan_filename = "2026-04-25_feat-file-search-history-md-viewer-and-plan-quick-search.md"

    # dev-runner: plan scope (registered paths)
    page.route(
        "**/api/v1/dev-runner/plans/paths",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\plan",
                        "type": "folder",
                        "plan_count": 1,
                        "path_type": "plan",
                    },
                    {
                        "path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive",
                        "type": "folder",
                        "plan_count": 0,
                        "path_type": "archive",
                    },
                ]
            ),
        ),
    )

    # dev-runner: runner status (used by PlanListTab onMount)
    page.route(
        "**/api/v1/dev-runner/status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "running": False,
                    "listener_alive": True,
                    "redis_connected": False,
                    "pid": None,
                    "plan_file": None,
                    "start_time": None,
                    "current_cycle": None,
                    "exit_code": None,
                    "crashed": False,
                    "current_plan_name": None,
                    "runner_id": None,
                }
            ),
        ),
    )

    # dev-runner: plan list (PlanListTab store fetchPlans)
    page.route(
        "**/api/v1/dev-runner/plans",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "path": plan_path,
                        "filename": plan_filename,
                        "status": "머지대기",
                        "progress": None,
                        "source": "common",
                        "ignored": False,
                        "path_type": "file",
                        "summary": "quick search stub",
                        "branch": None,
                        "worktree_path": None,
                        "worktree_owner": None,
                    }
                ]
            ),
        ),
    )

    # dev-runner: plan content (PlanViewer)
    page.route(
        "**/api/v1/dev-runner/plans/**/content",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "path": plan_path,
                    "content": "# Quick Search Plan\n\nThis is a stub.\n",
                }
            ),
        ),
    )

    # file-search: quick search request + poll
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
                    "result": {
                        "results": [
                            {
                                "file_path": plan_path,
                                "file_name": plan_filename,
                                "file_size": 512,
                                "modified": None,
                                "matches": [],
                                "match_source": "filename",
                            }
                        ],
                        "total_count": 1,
                        "search_time_ms": 12,
                        "mode": "both",
                        "truncated": False,
                    },
                    "error_message": None,
                }
            ),
        ),
    )

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=plans")
    page.wait_for_load_state("networkidle")

    page.get_by_placeholder("plan/archive 빠른 검색...").fill("file-search")
    page.get_by_role("button", name="검색", exact=True).click()

    expect(page.get_by_text(plan_filename, exact=True)).to_be_visible()
    page.get_by_text(plan_filename, exact=True).click()

    expect(page.get_by_role("heading", name="Quick Search Plan")).to_be_visible()
    # typography 통일 후 PlanViewer가 prose class wrapper를 가져야 한다
    expect(page.locator(".prose").first).to_be_visible()
    # raw <pre>만 존재하지 않음 (prose 내부 code block pre는 제외)
    expect(page.locator("pre:not(.prose pre)")).to_have_count(0)

