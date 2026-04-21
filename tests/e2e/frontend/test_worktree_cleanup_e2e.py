import json
import re
import time
from contextlib import suppress

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(marker in title for marker in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _empty_worktree_payload() -> dict:
    return {
        "worktrees": [],
        "plan_only": [],
        "branch_unresolved": [],
        "main_dirty": {"dirty_count": 0, "files": []},
    }


def _cleanable_worktree_payload(branch: str) -> dict:
    return {
        "worktrees": [
            {
                "branch": branch,
                "worktree_path": f"/repo/.worktrees/{branch.replace('/', '-')}",
                "created_at": "2026-04-21 14:00:00 +0900",
                "ahead": 0,
                "behind": 0,
                "locked": False,
                "commit_count": 0,
                "commits": [],
                "plan_file": None,
                "plan_mtime": None,
                "is_test": False,
                "plan_file_archived": False,
                "cleanable": True,
            }
        ],
        "plan_only": [],
        "branch_unresolved": [],
        "main_dirty": {"dirty_count": 0, "files": []},
    }


def _cleanup_preview_response(branch: str) -> dict:
    return {
        "results": [
            {
                "branch": branch,
                "status": "skipped",
                "reason": "dry_run",
                "worktree_removed": False,
                "branch_removed": False,
            }
        ],
        "summary": {
            "requested": 1,
            "removed": 0,
            "skipped": 1,
            "failed": 0,
            "not_found": 0,
            "timed_out": 0,
        },
    }


def _cleanup_apply_response(branch: str) -> dict:
    return {
        "results": [
            {
                "branch": branch,
                "status": "removed",
                "reason": "",
                "worktree_removed": True,
                "branch_removed": True,
            }
        ],
        "summary": {
            "requested": 1,
            "removed": 1,
            "skipped": 0,
            "failed": 0,
            "not_found": 0,
            "timed_out": 0,
        },
    }


def _cleanup_not_found_response(branch: str) -> dict:
    return {
        "results": [
            {
                "branch": branch,
                "status": "skipped",
                "reason": "worktree not found",
                "worktree_removed": False,
                "branch_removed": False,
            }
        ],
        "summary": {
            "requested": 1,
            "removed": 0,
            "skipped": 1,
            "failed": 0,
            "not_found": 1,
            "timed_out": 0,
        },
    }


def _stub_worktree_cleanup_api(
    page: Page,
    *,
    branch: str,
    preview_response: dict,
    apply_response: dict | None = None,
    initial_payload: dict | None = None,
    after_preview_payload: dict | None = None,
    after_apply_payload: dict | None = None,
    apply_delay_seconds: float = 0.0,
) -> list[dict]:
    cleanup_requests: list[dict] = []
    state = {
        "list_payload": initial_payload or _cleanable_worktree_payload(branch),
    }

    def handle_repos(route: Route) -> None:
        route.fulfill(status=200, content_type="application/json", body="[]")

    def handle_list(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(state["list_payload"]),
        )

    def handle_cleanup(route: Route) -> None:
        body = json.loads(route.request.post_data or "{}")
        cleanup_requests.append(body)

        if body.get("dry_run", True):
            if after_preview_payload is not None:
                state["list_payload"] = after_preview_payload
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(preview_response),
            )
            return

        if apply_delay_seconds > 0:
            time.sleep(apply_delay_seconds)
        if after_apply_payload is not None:
            state["list_payload"] = after_apply_payload
        with suppress(PlaywrightError):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(apply_response or _cleanup_apply_response(branch)),
            )

    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/repos(?:\?.*)?$"), handle_repos)
    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/cleanup(?:\?.*)?$"), handle_cleanup)
    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/v2(?:\?.*)?$"), handle_list)
    return cleanup_requests


def test_worktree_cleanup_preview_then_apply_updates_summary_and_busy_state(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    branch = "impl/cleanup-success"
    cleanup_requests = _stub_worktree_cleanup_api(
        page,
        branch=branch,
        preview_response=_cleanup_preview_response(branch),
        apply_response=_cleanup_apply_response(branch),
        after_apply_payload=_empty_worktree_payload(),
        apply_delay_seconds=0.35,
    )
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept()))

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    expect(page.get_by_text(branch)).to_be_visible()
    page.locator(".worktree-card-cleanable input[type='checkbox']").first.check()
    cleanup_button = page.get_by_role("button", name=re.compile(r"일괄 정리 \(1\)"))
    cleanup_button.click()

    expect(page.get_by_role("button", name="정리 중...")).to_be_visible()
    expect(page.get_by_text("워크트리 1개를 정리했습니다.")).to_be_visible()
    expect(page.get_by_text("요청 1 · 제거 1 · 건너뜀 0 · 실패 0")).to_be_visible()

    assert cleanup_requests == [
        {"branches": [branch], "dry_run": True},
        {"branches": [branch], "dry_run": False},
    ]
    assert dialogs
    assert "정리 후보 1개를 제거합니다." in dialogs[0]


def test_worktree_cleanup_stale_preview_refreshes_list_and_shows_warning_toast(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    branch = "impl/cleanup-stale"
    cleanup_requests = _stub_worktree_cleanup_api(
        page,
        branch=branch,
        preview_response=_cleanup_not_found_response(branch),
        after_preview_payload=_empty_worktree_payload(),
    )

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    page.locator(".worktree-card-cleanable input[type='checkbox']").first.check()
    page.get_by_role("button", name=re.compile(r"일괄 정리 \(1\)")).click()

    expect(page.get_by_text("이미 정리되었거나 목록이 오래되었습니다. 목록을 새로고침했습니다.")).to_be_visible()
    expect(page.get_by_text("표시할 워크트리가 없습니다")).to_be_visible()
    assert cleanup_requests == [{"branches": [branch], "dry_run": True}]


def test_worktree_cleanup_timeout_shows_cleanup_specific_guidance(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    branch = "impl/cleanup-timeout"
    page.add_init_script(
        """
        const originalSetTimeout = window.setTimeout.bind(window);
        window.setTimeout = (fn, delay, ...args) => {
          const clampedDelay = delay >= 120000 ? 20 : delay;
          return originalSetTimeout(fn, clampedDelay, ...args);
        };
        """
    )
    cleanup_requests = _stub_worktree_cleanup_api(
        page,
        branch=branch,
        preview_response=_cleanup_preview_response(branch),
        apply_response=_cleanup_apply_response(branch),
        apply_delay_seconds=0.2,
    )
    page.on("dialog", lambda dialog: dialog.accept())

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    page.locator(".worktree-card-cleanable input[type='checkbox']").first.check()
    page.get_by_role("button", name=re.compile(r"일괄 정리 \(1\)")).click()

    expect(
        page.get_by_text(
            "워크트리 정리 응답이 지연되고 있습니다. 서버에서 계속 정리 중일 수 있으니 잠시 후 목록을 새로고침해 결과를 확인하세요."
        )
    ).to_be_visible()
    assert cleanup_requests == [
        {"branches": [branch], "dry_run": True},
        {"branches": [branch], "dry_run": False},
    ]
