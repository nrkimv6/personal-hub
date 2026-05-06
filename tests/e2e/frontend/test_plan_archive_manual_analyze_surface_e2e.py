import json

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"current system mode={system_mode}; admin E2E skipped")


def _record_payload(**overrides):
    payload = {
        "id": 31,
        "filename_hash": "manual-analyze-31",
        "file_path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-05_manual-analyze.md",
        "project": "monitor-page",
        "title": "manual analyze fixture",
        "status": "archived",
        "memo": None,
        "memo_draft": None,
        "archived_at": "2026-05-05T01:00:00",
        "category": None,
        "tags": None,
        "summary": None,
        "superseded_by": None,
        "recurrence_count": 0,
        "chain_root_hash": None,
        "recurrence_suggestion": None,
        "llm_processed_at": None,
        "file_delete_after": None,
        "file_removed_at": None,
        "created_at": "2026-05-05T01:00:00",
        "updated_at": "2026-05-05T01:00:00",
    }
    payload.update(overrides)
    return payload


def _install_archive_routes(page: Page) -> dict[str, int]:
    calls = {"analyze": 0}

    def handle_api(route):
        url = route.request.url
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/plans/records/archive-health" in url:
            _json_response(
                route,
                {
                    "archived_total": 1,
                    "llm_processed": 0,
                    "llm_unprocessed": 1,
                    "real_unprocessed": 1,
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
                            "plan_record_relations",
                            "plan_record_search_runs",
                        ],
                        "missing_tables": [],
                    },
                },
            )
            return
        if "/api/v1/plans/records/31/content" in url:
            _json_response(route, {"id": 31, "raw_content": "# Manual analyze\n\nraw content"})
            return
        if (
            "/api/v1/plans/records" in url
            and "/analyze" not in url
            and "/content" not in url
            and "/archive-health" not in url
            and "/index" not in url
        ):
            _json_response(route, [_record_payload()])
            return
        if "/api/v1/plans/records/31/analyze" in url:
            calls["analyze"] += 1
            _json_response(route, {"success": False, "error": "ArchiveTab must not call manual analyze"})
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
            return
        if "/api/v1/plans/records/index" in url:
            _json_response(route, {"dry_run": True, "indexed": 0, "failed": 0, "skipped": 0, "run_id": None, "errors": []})
            return
        if "/api/v1/plans/retrieval/metrics" in url:
            _json_response(
                route,
                {
                    "total_plans": 1,
                    "followup_rates": {"days_7": 0, "days_14": 0, "days_30": 0},
                    "top_file_refs": [],
                    "missing_file_candidates": [],
                    "relation_counts": {},
                    "chain_depth_max": 0,
                },
            )
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)
    return calls


def test_archive_manual_analyze_surface_is_removed(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    calls = _install_archive_routes(page)

    page.goto(f"{frontend_url}/plans?tab=archive", wait_until="domcontentloaded")
    expect(page.get_by_text("2026-05-05_manual-analyze.md")).to_be_visible()
    page.locator("tbody tr").filter(has_text="2026-05-05_manual-analyze.md").evaluate("el => el.click()")
    expect(page.get_by_role("button", name="내용")).to_be_visible()
    expect(page.get_by_role("button", name="메모")).to_be_visible()
    expect(page.get_by_role("button", name="분석")).to_have_count(0)
    expect(page.get_by_text("Preview는 DB 저장 없음")).to_have_count(0)
    expect(page.get_by_role("button", name="DB 저장")).to_have_count(0)
    expect(page.get_by_text("LLM 분석 요청")).to_have_count(0)
    assert calls["analyze"] == 0
