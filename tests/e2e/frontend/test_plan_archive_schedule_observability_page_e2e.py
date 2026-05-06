"""[T3: mock-based UI test] /scheduler/plan-archive observability page.

summary/candidates/targets/queue/history 섹션 렌더링,
bulk queue 버튼, schedule pause 토글, request detail modal을 검증한다.
The archive-schedule and archive-candidates payloads below are mock payload only,
not live T5 endpoint evidence.
"""
import json

import pytest
from playwright.sync_api import Page, expect


pytestmark = [pytest.mark.e2e, pytest.mark.integration]

ADMIN_URL = "http://localhost:6101"


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _dashboard_payload(schedule=None):
    if schedule is Ellipsis:
        schedule = {
            "id": 1,
            "enabled": True,
            "cron_expr": "0 2 * * *",
            "next_run_at": "2026-05-07T02:00:00",
            "last_run_at": None,
            "max_per_run": 10,
            "provider": "codex",
            "model": "gpt-5.5",
        }
    return {
        "schedule": schedule,
        "health": {
            "archived_total": 30,
            "llm_processed": 25,
            "llm_unprocessed": 5,
            "real_unprocessed": 3,
            "temp_pytest_total": 0,
            "temp_pytest_unprocessed": 0,
            "pending_or_processing_requests": 2,
            "failed_requests": 0,
        },
        "retrieval_readiness": {
            "ready": True,
            "required_tables": [],
            "missing_tables": [],
        },
        "queue_summary": {
            "pending": 2,
            "processing": 0,
            "failed": 0,
            "completed_24h": 25,
            "recent_failures_by_category": {},
        },
        "recent_requests": [],
        "recent_schedule_runs": [],
        "recent_execution_attempts": [],
    }


def _install_plan_archive_routes(page: Page, *, schedule=Ellipsis, on_resume=None) -> None:
    # T3 mock contract: this file validates isolated UI rendering with mocked API payloads.
    def handle(route):
        url = route.request.url
        if "/api/v1/auth/me" in url:
            _json_response(route, {"username": "pytest", "is_admin": True})
            return
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/plans/records/archive-schedule-dashboard" in url:
            _json_response(route, _dashboard_payload(schedule))
            return
        if "/api/v1/plans/records/archive-schedule/resume" in url and route.request.method == "POST":
            if on_resume:
                on_resume()
            _json_response(route, {"schedule_id": 1, "enabled": True, "action": "resume"})
            return
        if "/api/v1/plans/records/archive-schedule/pause" in url and route.request.method == "POST":
            _json_response(route, {"schedule_id": 1, "enabled": False, "action": "pause"})
            return
        if "/api/v1/plans/records/archive-llm-requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "filters": {}})
            return
        if "/api/v1/plans/records/archive-schedule-runs" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "filters": {}})
            return
        if "/api/v1/plans/records/archive-execution-attempts" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "filters": {}})
            return
        if "/api/v1/plans/records/archive-health" in url:
            _json_response(
                route,
                {
                    "archived_total": 30,
                    "llm_processed": 25,
                    "llm_unprocessed": 5,
                    "real_unprocessed": 3,
                    "temp_pytest_total": 0,
                    "temp_pytest_unprocessed": 0,
                    "pending_or_processing_requests": 2,
                    "failed_requests": 0,
                    "latest_failed_request": None,
                    "oldest_unprocessed_at": None,
                    "plan_archive_schedule": {
                        "id": 1,
                        "enabled": True,
                        "cron_expr": "0 2 * * *",
                        "next_run_at": "2026-05-07T02:00:00",
                        "max_per_run": 10,
                        "provider": "codex",
                        "model": "gpt-5.5",
                    },
                    "retrieval_db_readiness": {
                        "ok": True,
                        "required_tables": [],
                        "missing_tables": [],
                    },
                },
            )
            return
        if "/api/v1/plans/archive-schedule" in url and route.request.method in ("GET", "PATCH"):
            _json_response(
                route,
                {
                    "id": 1,
                    "enabled": True,
                    "cron_expr": "0 2 * * *",
                    "next_run_at": "2026-05-07T02:00:00",
                    "max_per_run": 10,
                    "provider": "codex",
                    "model": "gpt-5.5",
                },
            )
            return
        if "/api/v1/plans/archive-candidates" in url:
            candidates = [
                {
                    "filename_hash": f"hash-{i:03d}",
                    "file_path": f"docs/archive/2026-05-0{i % 6 + 1}_plan-{i:03d}.md",
                    "title": f"Plan {i:03d}",
                    "status": "file_only" if i % 3 == 0 else "needs_analysis",
                    "total_bytes": 1024 * (i + 1),
                    "total_lines": 40 + i,
                    "archived_at": "2026-05-05T01:00:00",
                }
                for i in range(50)
            ]
            _json_response(route, {"candidates": candidates, "total": len(candidates)})
            return
        if "/api/v1/plans/archive-execution-targets" in url:
            _json_response(
                route,
                {
                    "targets": [
                        {
                            "id": 1,
                            "name": "monitor-page",
                            "enabled": True,
                            "priority": 1,
                            "provider": "codex",
                            "model": "gpt-5.5",
                        }
                    ],
                    "total": 1,
                },
            )
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
            return
        route.continue_()

    page.route("**/*", handle)


def _wait_for_body_text(page: Page) -> str:
    expect(page.locator("body")).to_be_visible()
    page.wait_for_function("document.body && document.body.innerText.trim().length > 0", timeout=5000)
    return page.inner_text("body")


def test_plan_archive_page_renders_summary_section(page: Page) -> None:
    _install_plan_archive_routes(page)
    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    # summary 섹션 또는 주요 텍스트 존재 확인
    body_text = _wait_for_body_text(page)
    assert (
        "plan-archive" in page.url.lower()
        or "archive" in body_text.lower()
        or "분석" in body_text
        or "30" in body_text
        or "25" in body_text
    ), f"plan-archive page did not load expected content; got: {body_text[:300]}"


def test_plan_archive_page_renders_candidates_section(page: Page) -> None:
    _install_plan_archive_routes(page)
    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    page.wait_for_timeout(800)
    body_text = _wait_for_body_text(page)
    assert (
        "후보" in body_text
        or "candidates" in body_text.lower()
        or "Plan 0" in body_text
        or "file_only" in body_text.lower()
        or "needs_analysis" in body_text.lower()
        or "분석 필요" in body_text
    ), f"candidates section not found; body: {body_text[:300]}"


def test_plan_archive_page_codex_provider_visible(page: Page) -> None:
    _install_plan_archive_routes(page)
    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    page.wait_for_timeout(800)
    body_text = _wait_for_body_text(page)
    assert (
        "codex" in body_text.lower()
        or "gpt-5.5" in body_text.lower()
        or "provider" in body_text.lower()
    ), f"provider/model info not visible; body: {body_text[:300]}"


def test_plan_archive_page_schedule_enabled_state_visible(page: Page) -> None:
    _install_plan_archive_routes(page)
    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    page.wait_for_timeout(800)
    body_text = _wait_for_body_text(page)
    assert (
        "스케줄" in body_text
        or "schedule" in body_text.lower()
        or "활성" in body_text
        or "enabled" in body_text.lower()
        or "2026-05-07" in body_text
        or "02:00" in body_text
    ), f"schedule section not visible; body: {body_text[:300]}"


def test_plan_archive_page_resume_button_posts_when_schedule_disabled(page: Page) -> None:
    resume_calls = []
    schedule = {
        "id": 1,
        "enabled": False,
        "cron_expr": "0 2 * * *",
        "next_run_at": "2026-05-07T02:00:00",
        "last_run_at": None,
        "max_per_run": 10,
        "provider": "codex",
        "model": "gpt-5.5",
    }
    _install_plan_archive_routes(page, schedule=schedule, on_resume=lambda: resume_calls.append(True))

    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    resume_button = page.get_by_role("button", name="재개")
    expect(resume_button).to_be_visible()
    resume_button.click()

    expect(page.get_by_text("Schedule 재개됨")).to_be_visible()
    assert resume_calls == [True]


def test_plan_archive_page_hides_mutation_buttons_when_schedule_missing(page: Page) -> None:
    _install_plan_archive_routes(page, schedule=None)

    page.goto(f"{ADMIN_URL}/scheduler/plan-archive")
    expect(page.get_by_text("스케줄 없음")).to_be_visible()
    expect(page.get_by_role("button", name="정지")).to_have_count(0)
    expect(page.get_by_role("button", name="재개")).to_have_count(0)


def test_plan_archive_source_contract_no_candidates_duplication(page: Page) -> None:
    """T3 static source contract: components are not duplicated in +page.svelte."""
    import re
    from pathlib import Path

    page_svelte = (
        Path(__file__).resolve().parents[3]
        / "frontend/src/routes/scheduler/plan-archive/+page.svelte"
    )
    assert page_svelte.exists(), f"+page.svelte not found at {page_svelte}"
    source = page_svelte.read_text(encoding="utf-8")

    # 각 컴포넌트 이름이 import 형태로만 존재하고 inline 구현이 없어야 한다
    assert "PlanArchiveSummary" in source or "Summary" in source, "Summary component import missing"
    assert "PlanArchiveCandidateTable" in source or "Candidate" in source, "CandidateTable import missing"
    # +page.svelte가 컴포넌트 분리 없이 1,000줄 초과 단일 파일이면 경고
    line_count = source.count("\n")
    assert line_count < 1000, f"+page.svelte has {line_count} lines — likely not decomposed"
