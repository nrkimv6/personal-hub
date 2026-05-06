import json

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"current system mode={system_mode}; admin E2E skipped")


def _install_readiness_missing_routes(page: Page) -> None:
    def handle_api(route):
        url = route.request.url
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        if "/api/v1/auth/me" in url:
            _json_response(route, {"username": "pytest", "is_admin": True})
            return
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/llm/providers" in url:
            _json_response(route, [])
            return
        if "/api/v1/plans/records/archive-health" in url:
            _json_response(
                route,
                {
                    "archived_total": 0,
                    "llm_processed": 0,
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
                        "required_tables": [],
                        "missing_tables": [],
                    },
                    "execution_db_readiness": {
                        "ok": False,
                        "required_tables": [
                            "plan_archive_execution_jobs",
                            "plan_archive_execution_attempts",
                            "llm_request_profile_claims",
                            "llm_profile_assignments",
                            "llm_schedule_profile_policies",
                        ],
                        "missing_tables": ["llm_schedule_profile_policies"],
                    },
                },
            )
            return
        if "/api/v1/plans/records?" in url:
            _json_response(route, [])
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)


def test_archive_tab_shows_execution_readiness_missing_warning(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _install_readiness_missing_routes(page)

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=archive", wait_until="domcontentloaded")

    expect(page.get_by_text("Plan Archive execution readiness missing")).to_be_visible()
    expect(page.get_by_text("llm_schedule_profile_policies")).to_be_visible()
