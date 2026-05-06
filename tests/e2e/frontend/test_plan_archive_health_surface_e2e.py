import json
import re

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


ARCHIVE_HEALTH = {
    "archived_total": 459,
    "llm_processed": 436,
    "llm_unprocessed": 23,
    "real_unprocessed": 12,
    "temp_pytest_total": 2,
    "temp_pytest_unprocessed": 1,
    "pending_or_processing_requests": 7,
    "failed_requests": 3,
    "latest_failed_request": {
        "id": 91,
        "caller_id": "archive-record-91",
        "requested_at": "2026-05-05T02:14:00",
        "error_message": "quota reset wait",
    },
    "oldest_unprocessed_at": "2026-04-01T09:30:00",
    "plan_archive_schedule": {
        "id": 1,
        "enabled": False,
        "schedule_value": '{"time":"02:10"}',
        "last_run": "2026-05-05T02:10:00",
        "last_success": "2026-05-04T02:12:00",
        "last_failure": "2026-05-05T02:12:00",
    },
}


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _install_plan_archive_routes(page: Page) -> None:
    def handle_api(route):
        url = route.request.url
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/auth/me" in url:
            _json_response(route, {"username": "pytest", "is_admin": True})
            return
        if "/api/v1/collect/schedules" in url:
            _json_response(
                route,
                [
                    {
                        "id": 1,
                        "name": "plan_archive_analyze_daily",
                        "display_name": "Plan Archive LLM 분석",
                        "target_type": "plan_archive_analyze",
                        "schedule_type": "cron",
                        "schedule_value": {"time": "02:10"},
                        "enabled": False,
                        "last_run_at": "2026-05-05T02:10:00",
                        "next_run_at": None,
                        "resolved_provider": "claude",
                        "resolved_model": "claude-opus-4-6",
                        "resolution_source": "caller_default",
                        "legacy_placeholder_candidate": False,
                    }
                ],
            )
            return
        if "/api/v1/plans/records/archive-health" in url:
            _json_response(route, ARCHIVE_HEALTH)
            return
        if "/api/v1/plans/records?" in url:
            _json_response(
                route,
                [
                    {
                        "id": 10,
                        "filename_hash": "archive-record-91",
                        "file_path": r"D:\work\project\tools\monitor-page\.worktrees\plans\docs\archive\2026-05-05_done.md",
                        "project": "monitor-page",
                        "title": "done archive",
                        "status": "완료",
                        "memo": None,
                        "memo_draft": None,
                        "archived_at": "2026-05-05T01:00:00",
                        "category": "bugfix",
                        "tags": [],
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
            _json_response(
                route,
                {
                    "items": [
                        {
                            "id": 91,
                            "caller_type": "plan_archive_analyze",
                            "caller_id": "archive-record-91",
                            "status": "failed",
                            "queue_name": "utility",
                            "requested_by": "scheduler",
                            "request_source": "plan_archive",
                            "provider": "claude",
                            "model": "claude-opus-4-6",
                            "requested_at": "2026-05-05T02:14:00",
                            "processed_at": None,
                            "result": None,
                            "error_message": "quota reset wait",
                            "retry_count": 1,
                            "raw_response": None,
                            "prompt": "analyze",
                            "cli_options": {"profile": "claude-work"},
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 50,
                    "pages": 1,
                },
            )
            return
        if "/api/v1/llm/providers" in url:
            _json_response(route, [{"key": "claude", "display_name": "Claude", "models": []}])
            return
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"current system mode={system_mode}; admin E2E skipped")


def test_scheduler_plan_archive_card_uses_compact_alert(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _install_plan_archive_routes(page)

    page.goto(f"{frontend_url}/scheduler", wait_until="domcontentloaded")

    expect(page.get_by_text("Plan Archive LLM 분석")).to_be_visible()
    expect(page.get_by_text("미처리 12건, 스케줄 비활성")).to_be_visible()
    expect(page.get_by_text("Plan Archive 상세")).to_be_visible()
    expect(page.get_by_text("실제 미처리")).to_have_count(0)
    expect(page.get_by_text("큐 대기/처리중")).to_have_count(0)
    expect(page.get_by_text("마지막 성공")).to_have_count(0)

    page.get_by_role("button", name="수정").click()
    expect(page.get_by_text("LLM 설정")).to_be_visible()
    expect(page.get_by_label("LLM Provider")).to_be_visible()


def test_archive_tab_does_not_expose_health_and_queue_surface(
    page: Page,
    frontend_url: str,
    system_mode: str,
):
    _skip_admin_mode_if_public(system_mode)
    _install_plan_archive_routes(page)

    page.goto(f"{frontend_url}/automation?tab=plans&subtab=archive", wait_until="domcontentloaded")

    expect(page.get_by_text("이 화면은 archive 파일/DB 관리 전용입니다.")).to_be_visible()
    expect(page.get_by_role("link", name="/scheduler/plan-archive")).to_be_visible()
    expect(page.get_by_text("Plan Archive LLM health")).to_have_count(0)
    expect(page.get_by_text("Real backlog")).to_have_count(0)
    expect(page.get_by_text("비활성 때문에 backlog가 쌓일 수 있습니다.")).to_have_count(0)
    expect(page.get_by_text("quota reset wait")).to_have_count(0)
    expect(page.get_by_text("pending_or_processing_requests는 현재 활성 LLMRequest 수입니다.")).to_have_count(0)
    expect(page.get_by_text("Plan Archive LLM 요청")).to_have_count(0)
    expect(page.get_by_text("archive-record-91")).to_have_count(0)
    expect(page.get_by_text("claude / claude-opus-4-6")).to_have_count(0)
    expect(page.get_by_role("cell", name=re.compile(r"claude-work"))).to_have_count(0)
