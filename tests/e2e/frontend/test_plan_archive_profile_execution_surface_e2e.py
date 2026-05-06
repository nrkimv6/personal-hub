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
        "id": 41,
        "filename_hash": "profile-exec-41",
        "file_path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-06_profile-exec.md",
        "project": "monitor-page",
        "title": "profile execution fixture",
        "status": "archived",
        "memo": None,
        "memo_draft": None,
        "archived_at": "2026-05-06T01:00:00",
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
        "archive_state": "archived",
        "execution_state": "blocked",
        "latest_attempt": None,
        "next_available_at": "2026-05-06T03:10:00",
        "created_at": "2026-05-06T01:00:00",
        "updated_at": "2026-05-06T01:00:00",
    }
    payload.update(overrides)
    return payload


def _install_archive_execution_routes(page: Page) -> dict[str, object]:
    calls: dict[str, object] = {"run": 0, "sync": 0, "run_payloads": []}

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
        if "/api/v1/llm/profiles" in url and "/status" not in url:
            _json_response(
                route,
                {
                    "selected": {"claude": "work"},
                    "supported_engines": ["claude"],
                    "profiles": [
                        {
                            "engine": "claude",
                            "name": "work",
                            "config_dir": None,
                            "extra_env": {},
                            "enabled": True,
                            "priority": 1,
                            "capacity": 1,
                        }
                    ],
                },
            )
            return
        if "/api/v1/llm/providers" in url:
            _json_response(
                route,
                [
                    {
                        "key": "claude",
                        "display_name": "Claude",
                        "default_model": "claude-opus-4-5",
                        "models": ["claude-opus-4-5", "claude-sonnet-4-5"],
                    }
                ],
            )
            return
        if "/api/v1/llm/schedule-profile-policies" in url:
            _json_response(
                route,
                {
                    "policies": [
                        {
                            "id": 1,
                            "target_type": "plan_archive_analyze",
                            "engine": "claude",
                            "profile_name": "work",
                            "enabled": True,
                            "priority": 1,
                            "allowed_windows": [],
                            "quiet_windows": [],
                        }
                    ]
                },
            )
            return
        if "/api/v1/plans/records/archive-schedule-dashboard" in url:
            _json_response(
                route,
                {
                    "schedule": {
                        "id": 1,
                        "enabled": True,
                        "next_run_at": "2026-05-06T03:00:00",
                        "last_run_at": "2026-05-06T02:00:00",
                    },
                    "health": {},
                    "retrieval_readiness": {"ready": True, "missing_tables": []},
                    "queue_summary": {
                        "pending": 1,
                        "processing": 0,
                        "failed": 1,
                        "completed_24h": 2,
                        "recent_failures_by_category": {"quota": 1},
                    },
                    "recent_requests": [],
                    "recent_schedule_runs": [],
                    "recent_execution_attempts": [],
                },
            )
            return
        if "/api/v1/plans/records/archive-candidates" in url and "/queue" not in url and "/preview" not in url:
            _json_response(route, {"candidates": []})
            return
        if "/api/v1/plans/records/archive-executions/run" in url:
            calls["run"] += 1
            calls["run_payloads"].append(route.request.post_data_json)
            _json_response(
                route,
                {
                    "queued": 1,
                    "skipped": 0,
                    "request_ids": [902],
                    "attempts": [
                        {
                            "id": 502,
                            "record_id": 41,
                            "llm_request_id": 902,
                            "engine": "claude",
                            "profile_name": "work",
                            "status": "queued",
                            "requested_at": "2026-05-06T02:05:00",
                        }
                    ],
                },
            )
            return
        if "/api/v1/plans/records/archive-executions/sync" in url:
            calls["sync"] += 1
            _json_response(route, {"updated": 1, "records": [_record_payload(execution_state="queued")], "errors": []})
            return
        if "/api/v1/plans/records/archive-executions/history" in url:
            _json_response(
                route,
                {
                    "items": [
                        {
                            "id": 501,
                            "record_id": 41,
                            "llm_request_id": 901,
                            "engine": "claude",
                            "profile_name": "work",
                            "status": "blocked",
                            "requested_at": "2026-05-06T02:00:00",
                            "error_message": "capacity full",
                        }
                    ],
                    "total": 1,
                    "limit": 20,
                    "record_id": 41,
                },
            )
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
                    "pending_or_processing_requests": 1,
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
                            "plan_archive_execution_jobs",
                            "plan_archive_execution_attempts",
                        ],
                        "missing_tables": [],
                    },
                },
            )
            return
        if "/api/v1/plans/records?" in url:
            _json_response(route, [_record_payload()])
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
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
                    "repo_counts": {},
                    "cross_repo_plan_count": 0,
                    "multi_repo_plan_count": 0,
                    "downstream_sync_missing_candidates": [],
                },
            )
            return
        if "/api/v1/plans/records/index" in url:
            _json_response(route, {"dry_run": True, "indexed": 0, "failed": 0, "skipped": 0, "run_id": None, "errors": []})
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)
    return calls


def test_archive_profile_execution_controls_and_capacity_state(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    calls = _install_archive_execution_routes(page)
    page.add_init_script("localStorage.clear()")

    page.goto(f"{frontend_url}/scheduler/plan-archive", wait_until="domcontentloaded")

    expect(page.get_by_text("Archive Schedule 현황")).to_be_visible()
    expect(page.get_by_text("분석 Target:")).to_be_visible()
    expect(page.get_by_text("target을 1개 이상 선택하세요")).to_be_visible()
    page.get_by_role("button", name="0개 선택됨").click()
    page.get_by_label("claude/work/claude-opus-4-5 model").select_option("claude-sonnet-4-5")
    page.get_by_role("button", name="claude/work/claude-sonnet-4-5").click()
    expect(page.locator('button[title="claude/work/claude-sonnet-4-5"]').first).to_be_visible()
    expect(page.get_by_role("button", name="Backlog 실행")).to_be_enabled()
    expect(page.get_by_text("quota 1")).to_be_visible()

    page.get_by_role("button", name="Sync").click()
    expect(page.get_by_text("동기화 1건", exact=True)).to_be_visible()
    assert calls["sync"] == 1

    page.get_by_role("button", name="Backlog 실행").click()
    expect(page.get_by_text("큐잉 1건", exact=True)).to_be_visible()
    assert calls["run"] == 1
    assert calls["run_payloads"] == [
        {
            "selected_targets": [
                {
                    "provider": "claude",
                    "model": "claude-sonnet-4-5",
                    "profile_key": "claude:work",
                    "engine": "claude",
                    "profile_name": "work",
                    "label": "claude/work/claude-sonnet-4-5",
                    "kind": "profile",
                }
            ]
        }
    ]
