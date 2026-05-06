import re

import pytest
from playwright.sync_api import Page, Route, expect


def _skip_admin_mode_if_public(system_mode: str):
    if system_mode == "public":
        pytest.skip("admin-only archive UI is not mounted in public mode")


@pytest.fixture
def archive_cross_repo_page(page: Page, frontend_url: str, system_mode: str):
    _skip_admin_mode_if_public(system_mode)

    def route_api(route: Route):
        url = route.request.url
        if "/api/v1/plans/records/archive-health" in url:
            route.fulfill(
                status=200,
                json={
                    "archived_total": 1,
                    "llm_processed": 1,
                    "llm_unprocessed": 0,
                    "real_unprocessed": 0,
                    "temp_pytest_total": 0,
                    "temp_pytest_unprocessed": 0,
                    "pending_or_processing_requests": 0,
                    "failed_requests": 0,
                    "file_retention_due": 0,
                    "file_retention_scheduled": 0,
                    "file_removed": 0,
                    "oldest_file_delete_after": None,
                    "latest_failed_request": None,
                    "oldest_unprocessed_at": None,
                    "plan_archive_schedule": None,
                    "retrieval_db_readiness": {
                        "ok": True,
                        "required_tables": [
                            "plan_record_chunks",
                            "plan_record_file_refs",
                            "plan_record_repo_refs",
                            "plan_record_relations",
                            "plan_record_search_runs",
                        ],
                        "missing_tables": [],
                    },
                },
            )
            return
        if "/api/v1/plans/records?" in url or url.endswith("/api/v1/plans/records"):
            route.fulfill(
                status=200,
                json=[
                    {
                        "id": 42,
                        "filename_hash": "hash-cross",
                        "file_path": "docs/archive/2026-05-05-cross.md",
                        "project": "monitor-page",
                        "title": "Plan Archive cross repo",
                        "status": "archived",
                        "memo": None,
                        "memo_draft": None,
                        "archived_at": "2026-05-05T00:00:00",
                        "category": "infra",
                        "tags": [],
                        "summary": None,
                        "superseded_by": None,
                        "recurrence_count": 1,
                        "chain_root_hash": None,
                        "recurrence_suggestion": None,
                        "llm_processed_at": None,
                        "file_delete_after": None,
                        "file_removed_at": None,
                        "created_at": "2026-05-05T00:00:00",
                        "updated_at": "2026-05-05T00:00:00",
                    }
                ],
            )
            return
        if "/api/v1/plans/retrieval/search" in url:
            route.fulfill(
                status=200,
                json={
                    "total": 1,
                    "results": [
                        {
                            "plan": {
                                "id": 42,
                                "filename_hash": "hash-cross",
                                "file_path": "docs/archive/2026-05-05-cross.md",
                                "title": "Plan Archive cross repo",
                                "status": "archived",
                                "category": "infra",
                                "tags": [],
                                "summary": None,
                                "intent": None,
                                "scope": None,
                                "archived_at": "2026-05-05T00:00:00",
                            },
                            "score": 120,
                            "score_detail": {"file": 100},
                            "chunks": [],
                            "file_refs": [
                                {
                                    "id": 7,
                                    "path": "common/skills/implement/SKILL.md",
                                    "source_type": "downstream_sync",
                                    "repo_key": "wtools",
                                    "module": "common/skills",
                                    "commit_sha": "abc123",
                                    "exists_at_index": True,
                                }
                            ],
                        }
                    ],
                },
            )
            return
        if "/api/v1/plans/retrieval/metrics" in url:
            route.fulfill(
                status=200,
                json={
                    "total_plans": 1,
                    "followup_rates": {"days_7": 0, "days_14": 0, "days_30": 0},
                    "top_file_refs": [
                        {
                            "path": "common/skills/implement/SKILL.md",
                            "repo_key": "wtools",
                            "count": 1,
                            "mentioned_count": 0,
                            "changed_count": 1,
                        }
                    ],
                    "missing_file_candidates": [],
                    "relation_counts": {},
                    "chain_depth_max": 1,
                    "repo_counts": {"wtools": 1},
                    "cross_repo_plan_count": 1,
                    "multi_repo_plan_count": 1,
                    "downstream_sync_missing_candidates": [
                        {"repo_key": "wtools", "path": "common/skills/implement/SKILL.md", "count": 1}
                    ],
                },
            )
            return
        if "/api/v1/plans/retrieval/cross-repo/index" in url:
            route.fulfill(
                status=200,
                json={
                    "dry_run": True,
                    "record_id": 42,
                    "repos": 2,
                    "indexed": 1,
                    "failed": 0,
                    "skipped": 0,
                    "errors": [],
                },
            )
            return
        route.fallback()

    page.route(re.compile(r".*/api/v1/plans/.*"), route_api)
    page.route(re.compile(r".*/api/v1/llm/requests.*"), lambda route: route.fulfill(status=200, json={"items": [], "page": 1, "pages": 1, "total": 0}))
    page.route(re.compile(r".*/api/v1/dev-runner/plans.*"), lambda route: route.fulfill(status=200, json=[]))
    page.goto(f"{frontend_url}/plans?tab=archive", wait_until="domcontentloaded")
    expect(page.get_by_text("Plan Archive retrieval")).to_be_visible()
    return page


@pytest.mark.e2e
def test_archive_cross_repo_surface_renders_repo_filter_badge_and_warning(archive_cross_repo_page: Page):
    page = archive_cross_repo_page

    expect(page.get_by_placeholder("repo_key")).to_be_visible()
    page.get_by_placeholder("repo_key").fill("wtools")
    page.get_by_role("button", name="retrieval 검색").click()

    expect(page.get_by_text("wtools · downstream_sync")).to_be_visible()
    expect(page.get_by_text("Repo evidence")).to_be_visible()
    expect(page.get_by_text("Downstream sync evidence 후보")).to_be_visible()


@pytest.mark.e2e
def test_archive_cross_repo_surface_runs_dry_run_for_selected_record(archive_cross_repo_page: Page):
    page = archive_cross_repo_page

    page.get_by_text("Plan Archive cross repo").first.click()
    expect(page.get_by_text("Cross-repo index")).to_be_visible()
    page.get_by_role("button", name="cross dry-run").click()
    expect(page.get_by_text("repos 2")).to_be_visible()
