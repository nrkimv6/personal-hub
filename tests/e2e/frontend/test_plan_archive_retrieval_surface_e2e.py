import json

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"current system mode={system_mode}; admin E2E skipped")


def _install_archive_routes(page: Page) -> dict[str, int]:
    calls = {"index_apply": 0, "index_dry_run": 0}

    def handle_api(route):
        url = route.request.url
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/auth/me" in url:
            _json_response(route, {"username": "pytest", "is_admin": True})
            return
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        if "/api/v1/plans/records/archive-health" in url:
            _json_response(
                route,
                {
                    "archived_total": 12,
                    "llm_processed": 10,
                    "llm_unprocessed": 2,
                    "real_unprocessed": 1,
                    "temp_pytest_total": 0,
                    "temp_pytest_unprocessed": 0,
                    "pending_or_processing_requests": 0,
                    "failed_requests": 0,
                    "latest_failed_request": None,
                    "oldest_unprocessed_at": None,
                    "plan_archive_schedule": None,
                    "retrieval_db_readiness": {
                        "ok": True,
                        "required_tables": [
                            "plan_record_chunks",
                            "plan_record_file_refs",
                            "plan_record_relations",
                            "plan_record_search_runs",
                        ],
                        "missing_tables": [],
                    },
                },
            )
            return
        if "/api/v1/plans/records?" in url:
            _json_response(
                route,
                [
                    {
                        "id": 21,
                        "filename_hash": "archive-21",
                        "file_path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-05_done-plan.md",
                        "project": "monitor-page",
                        "title": "archived retrieval seed",
                        "status": "archived",
                        "memo": None,
                        "memo_draft": None,
                        "archived_at": "2026-05-05T01:00:00",
                        "category": "feature",
                        "tags": ["archive"],
                        "summary": None,
                        "superseded_by": None,
                        "recurrence_count": 0,
                        "chain_root_hash": None,
                        "recurrence_suggestion": None,
                        "llm_processed_at": None,
                        "created_at": "2026-05-05T01:00:00",
                        "updated_at": "2026-05-05T01:00:00",
                    }
                ],
            )
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
            return
        if "/api/v1/plans/retrieval/search" in url:
            _json_response(
                route,
                {
                    "total": 1,
                    "results": [
                        {
                            "plan": {
                                "id": 101,
                                "title": "Plan Archive retrieval index MVP",
                                "file_path": r"docs\archive\2026-05-05_feat-plan-archive-retrieval-index-mvp.md",
                            },
                            "score": 0.91,
                            "score_detail": {"lexical": 0.7, "file": 0.21},
                            "chunks": [
                                {
                                    "id": 301,
                                    "section_type": "todo",
                                    "heading": "Archive UI",
                                    "text": "검색 결과에 evidence chunk와 source id를 표시한다.",
                                    "snippet": "evidence chunk와 source id를 표시한다.",
                                    "score": 0.86,
                                }
                            ],
                            "file_refs": [
                                {
                                    "id": 401,
                                    "path": "frontend/src/routes/plans/ArchiveTab.svelte",
                                    "source_type": "mentioned_in_plan",
                                    "module": "frontend",
                                    "exists_at_index": True,
                                }
                            ],
                        }
                    ],
                },
            )
            return
        if "/api/v1/plans/retrieval/metrics" in url:
            _json_response(
                route,
                {
                    "total_plans": 42,
                    "followup_rates": {"days_7": 0.25, "days_14": 0.5, "days_30": 0.75},
                    "top_file_refs": [
                        {
                            "path": "frontend/src/routes/plans/ArchiveTab.svelte",
                            "count": 7,
                            "mentioned_count": 5,
                            "changed_count": 2,
                        }
                    ],
                    "missing_file_candidates": [
                        {
                            "module": "frontend",
                            "count": 3,
                            "paths": ["frontend/src/lib/api/plan-records.ts"],
                        }
                    ],
                    "relation_counts": {"followup": 4},
                    "chain_depth_max": 3,
                },
            )
            return
        if "/api/v1/plans/records/index" in url:
            payload = route.request.post_data_json
            if payload.get("apply"):
                calls["index_apply"] += 1
                _json_response(route, {"dry_run": False, "indexed": 9, "failed": 0, "skipped": 1, "run_id": 77, "errors": []})
            else:
                calls["index_dry_run"] += 1
                _json_response(route, {"dry_run": True, "indexed": 9, "failed": 0, "skipped": 1, "run_id": None, "errors": []})
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)
    return calls


def test_archive_retrieval_surface_renders_search_evidence_and_metrics(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _install_archive_routes(page)

    page.goto(f"{frontend_url}/plans?tab=archive", wait_until="domcontentloaded")

    expect(page.get_by_text("Plan Archive retrieval")).to_be_visible()
    expect(page.get_by_text("14d follow-up")).to_be_visible()
    expect(page.get_by_text("50%")).to_be_visible()
    expect(page.get_by_text("Top file refs")).to_be_visible()
    expect(page.get_by_text("frontend/src/routes/plans/ArchiveTab.svelte").first).to_be_visible()
    expect(page.get_by_text("누락 후보 파일군")).to_be_visible()

    page.get_by_placeholder("키워드, 파일명, 함수명").fill("evidence")
    page.get_by_placeholder("파일 경로 filter").fill("ArchiveTab.svelte")
    page.get_by_role("button", name="retrieval 검색").click()

    expect(page.get_by_text("Plan Archive retrieval index MVP")).to_be_visible()
    expect(page.get_by_text("chunk #301")).to_be_visible()
    expect(page.get_by_text("evidence chunk와 source id를 표시한다.")).to_be_visible()
    expect(page.get_by_text("#401 mentioned_in_plan: frontend/src/routes/plans/ArchiveTab.svelte")).to_be_visible()


def test_archive_index_apply_requires_dry_run_result(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    calls = _install_archive_routes(page)

    page.goto(f"{frontend_url}/plans?tab=archive", wait_until="domcontentloaded")

    apply_button = page.get_by_role("button", name="apply index")
    expect(apply_button).to_be_disabled()
    assert calls["index_apply"] == 0

    page.get_by_role("button", name="dry-run").click()
    expect(page.get_by_text("indexed 9", exact=True)).to_be_visible()
    expect(apply_button).to_be_enabled()

    apply_button.click()
    expect(page.get_by_text("run #77")).to_be_visible()
    assert calls["index_dry_run"] == 1
    assert calls["index_apply"] == 1
