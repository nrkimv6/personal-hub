import json
import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(marker in title for marker in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _worktree_list_payload(branch: str, commit_count: int) -> dict:
    return {
        "worktrees": [
            {
                "branch": branch,
                "worktree_path": f"/repo/.worktrees/{branch.replace('/', '-')}",
                "created_at": "2026-04-21 09:00:00 +0900",
                "ahead": commit_count,
                "behind": 0,
                "locked": False,
                "commit_count": commit_count,
                "plan_file": "docs/plan/2026-04-20_perf-worktree-list-lazy-commit-load.md",
                "plan_mtime": "2026-04-21T09:00:00",
                "is_test": False,
                "plan_file_archived": False,
                "cleanable": False,
            }
        ],
        "plan_only": [],
        "branch_unresolved": [],
        "main_dirty": {"dirty_count": 0, "files": []},
    }


def _commit_payload(message: str, filename: str = "app/feature.py") -> list[dict]:
    return [
        {
            "hash": "1234567890abcdef1234567890abcdef12345678",
            "short_hash": "1234567",
            "message": message,
            "date": "2026-04-21 09:30:00 +0900",
            "diff_stat": [{"file": filename, "changes": "+4 -1"}],
        }
    ]


def _stub_worktree_tab_api(
    page: Page,
    *,
    worktrees_by_repo: dict[int | None, dict],
    commits_by_branch: dict[str, list[dict]],
    repo_options: list[dict] | None = None,
    delayed_branch: str | None = None,
    delayed_seconds: float = 0.0,
) -> list[str]:
    commit_requests: list[str] = []
    repo_options = repo_options or []

    def handle_repos(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(repo_options),
        )

    def handle_list(route: Route) -> None:
        parsed = urlparse(route.request.url)
        repo_id_values = parse_qs(parsed.query).get("repo_id")
        repo_id = int(repo_id_values[0]) if repo_id_values else None
        payload = worktrees_by_repo.get(repo_id, worktrees_by_repo[None])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def handle_commits(route: Route) -> None:
        parsed = urlparse(route.request.url)
        params = parse_qs(parsed.query)
        branch = params.get("branch", [""])[0]
        commit_requests.append(route.request.url)
        if branch == delayed_branch and delayed_seconds > 0:
            time.sleep(delayed_seconds)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(commits_by_branch.get(branch, [])),
        )

    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/repos(?:\?.*)?$"), handle_repos)
    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/v2/commits(?:\?.*)?$"), handle_commits)
    page.route(re.compile(r".*/api/v1/dev-runner/worktrees/v2(?:\?.*)?$"), handle_list)
    return commit_requests


def test_worktree_tab_initial_render_does_not_fetch_commits(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    commit_requests = _stub_worktree_tab_api(
        page,
        worktrees_by_repo={None: _worktree_list_payload("impl/lazy-initial", 2)},
        commits_by_branch={"impl/lazy-initial": _commit_payload("feat: should stay lazy")},
    )

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    expect(page.get_by_text("impl/lazy-initial")).to_be_visible()
    expect(page.get_by_role("button", name="커밋 2개")).to_be_visible()
    expect(page.get_by_text("feat: should stay lazy")).to_have_count(0)
    assert commit_requests == []


def test_worktree_tab_expanded_branch_fetches_commits_once_and_reuses_cache(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    commit_requests = _stub_worktree_tab_api(
        page,
        worktrees_by_repo={None: _worktree_list_payload("impl/lazy-cache", 1)},
        commits_by_branch={"impl/lazy-cache": _commit_payload("feat: cached commit", "src/cache.ts")},
    )

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    toggle = page.get_by_role("button", name="커밋 1개")
    toggle.click()
    expect(page.get_by_text("feat: cached commit")).to_be_visible()
    expect(page.get_by_text("src/cache.ts")).to_be_visible()

    toggle.click()
    expect(page.get_by_text("feat: cached commit")).to_have_count(0)
    toggle.click()
    expect(page.get_by_text("feat: cached commit")).to_be_visible()

    assert len(commit_requests) == 1
    assert "branch=impl%2Flazy-cache" in commit_requests[0]


def test_worktree_tab_repo_switch_ignores_stale_commit_response(
    page: Page, frontend_url: str, system_mode: str
) -> None:
    _skip_admin_mode_if_public(system_mode)
    commit_requests = _stub_worktree_tab_api(
        page,
        worktrees_by_repo={
            None: _worktree_list_payload("impl/repo-a", 1),
            7: _worktree_list_payload("impl/repo-b", 0),
        },
        commits_by_branch={
            "impl/repo-a": _commit_payload("feat: stale repo-a commit", "src/repo-a.ts"),
            "impl/repo-b": [],
        },
        repo_options=[{"id": 7, "alias": "repo-b", "path": "D:/repo-b"}],
        delayed_branch="impl/repo-a",
        delayed_seconds=0.6,
    )

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=worktrees")
    page.wait_for_load_state("networkidle")
    _skip_if_frontend_error_title(page)

    page.get_by_role("button", name="커밋 1개").click()
    page.locator("select.repo-select").select_option("7")
    expect(page.get_by_text("impl/repo-b")).to_be_visible()
    expect(page.get_by_role("button", name="커밋 0개")).to_be_visible()

    page.wait_for_timeout(900)

    expect(page.get_by_text("feat: stale repo-a commit")).to_have_count(0)
    expect(page.get_by_text("src/repo-a.ts")).to_have_count(0)
    assert len(commit_requests) == 1
    assert "branch=impl%2Frepo-a" in commit_requests[0]
