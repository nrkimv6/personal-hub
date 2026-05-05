"""LLM / scheduler runtime smoke tests."""

import json
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _assert_no_loading_spinner(page: Page) -> None:
    expect(page.locator(".animate-spin")).to_have_count(0, timeout=15000)


def _wait_for_runtime_page(page: Page) -> None:
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("main").first).to_be_visible(timeout=15000)


def _json_response(route, payload) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _llm_bootstrap_payload() -> dict:
    request = {
        "id": 501,
        "caller_type": "plan_archive_analyze",
        "caller_id": "quota-window-e2e",
        "status": "pending",
        "queue_name": "utility",
        "requested_by": "pytest",
        "request_source": "e2e",
        "provider": "claude",
        "model": "claude-opus-4-6",
        "requested_at": "2026-05-05T21:00:00",
        "processed_at": None,
        "result": None,
        "error_message": None,
        "retry_count": 0,
        "raw_response": None,
        "prompt": "quota window badge",
        "cli_options": {},
    }
    return {
        "list": {"items": [request], "total": 1, "page": 1, "page_size": 20, "pages": 1},
        "stats": {"total": 1, "pending": 1, "processing": 0, "completed": 0, "failed": 0},
        "queue_stats": {
            "system": {"pending": 0, "processing": 0, "completed": 0, "failed": 0},
            "utility": {"pending": 1, "processing": 0, "completed": 0, "failed": 0},
        },
        "worker_status": {
            "status": "healthy",
            "worker_id": "pytest",
            "state": "idle",
            "processed_count": 0,
            "message": "ready",
            "seconds_since_heartbeat": 1,
        },
    }


def _install_llm_routes(page: Page, quota_status: dict) -> None:
    def handle_api(route):
        url = route.request.url
        if "/api/v1/llm/bootstrap" in url:
            _json_response(route, _llm_bootstrap_payload())
            return
        if "/api/v1/llm/quota-status" in url:
            _json_response(route, quota_status)
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        _json_response(route, {})

    page.route("**/api/v1/**", handle_api)


def _install_profile_pool_routes(page: Page, calls: list[str]) -> None:
    profiles_payload = {
        "selected": {"claude": "work", "gemini": "default"},
        "profiles": [
            {
                "engine": "claude",
                "name": "work",
                "config_dir": None,
                "extra_env": {},
                "enabled": True,
                "priority": 100,
                "last_quota_pause_until": "2026-05-05T23:00:00",
                "last_reset_at": None,
                "last_state": "paused_by_quota",
                "last_error_summary": "quota",
            },
            {
                "engine": "claude",
                "name": "personal",
                "config_dir": None,
                "extra_env": {},
                "enabled": True,
                "priority": 10,
                "last_quota_pause_until": None,
                "last_reset_at": "2026-05-05T20:00:00",
                "last_state": "available",
                "last_error_summary": None,
            },
            {
                "engine": "gemini",
                "name": "default",
                "config_dir": None,
                "extra_env": {},
                "enabled": False,
                "priority": 0,
                "last_quota_pause_until": None,
                "last_reset_at": None,
                "last_state": "disabled",
                "last_error_summary": None,
            },
        ],
        "supported_engines": ["claude", "gemini"],
    }
    status_payload = [
        {
            "engine": "claude",
            "profile_name": "work",
            "enabled": True,
            "priority": 100,
            "state": "paused_by_quota",
            "paused_until": "2026-05-05T23:00:00",
            "last_reset_at": None,
            "last_error_summary": "quota",
        },
        {
            "engine": "claude",
            "profile_name": "personal",
            "enabled": True,
            "priority": 10,
            "state": "available",
            "paused_until": None,
            "last_reset_at": "2026-05-05T20:00:00",
            "last_error_summary": None,
        },
    ]

    def handle_profiles(route):
        calls.append(f"{route.request.method} {route.request.url}")
        _json_response(route, profiles_payload)

    def handle_status(route):
        calls.append(f"{route.request.method} {route.request.url}")
        _json_response(route, status_payload)

    def handle_pause(route):
        calls.append(f"{route.request.method} {route.request.url}")
        _json_response(route, {"ok": True})

    page.route("**/api/v1/llm/profiles/status", handle_status)
    page.route("**/api/v1/llm/profiles/*/*/pause", handle_pause)
    page.route("**/api/v1/llm/profiles", handle_profiles)


class TestLlmRuntime:
    def test_llm_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/llm")
        _wait_for_runtime_page(page)

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert (
            page.get_by_text("대기열이 비어있습니다").count() > 0
            or page.get_by_text("이력이 없습니다").count() > 0
            or page.get_by_text("이력 보기").count() > 0
            or page.locator("table tbody tr").count() > 0
        ), "LLM 화면이 빈 상태로 남아있거나 목록이 렌더되지 않았습니다"

    @pytest.mark.parametrize(
        ("quota_status", "badge_text", "modal_text"),
        [
            (
                {
                    "claude": {
                        "paused": True,
                        "until": "2026-05-05T23:00:00+09:00",
                        "reason": "Claude quota resets 11:00pm",
                        "remaining_seconds": 3600,
                        "pending_blocked_count": 1,
                        "timezone": "Asia/Seoul",
                    }
                },
                "쿼터 보류",
                None,
            ),
            (
                {
                    "__execution_window": {
                        "paused": True,
                        "until": "2026-05-06T07:30:00+09:00",
                        "reason": "outside execution window",
                        "remaining_seconds": 1800,
                        "pending_blocked_count": 1,
                        "timezone": "Asia/Seoul",
                    }
                },
                "시간창 보류",
                "시간창 보류",
            ),
        ],
    )
    def test_pending_rows_show_quota_or_window_pause_badge(
        self,
        page: Page,
        frontend_url: str,
        quota_status: dict,
        badge_text: str,
        modal_text: str | None,
    ):
        _install_llm_routes(page, quota_status)

        page.goto(f"{frontend_url}/llm", wait_until="domcontentloaded")

        badge = page.get_by_text(badge_text).first
        expect(badge).to_be_visible()
        if modal_text:
            page.get_by_text("quota-window-e2e").click()
            expect(page.get_by_text(modal_text).first).to_be_visible()

    def test_profile_policy_matrix_save_and_pending_reason_badge(self, page: Page, frontend_url: str):
        calls: list[str] = []
        request = {
            **_llm_bootstrap_payload()["list"]["items"][0],
            "pending_block_reason": "schedule_policy_off",
            "error_message": "schedule_policy_off",
        }
        profiles_payload = {
            "selected": {"claude": "work"},
            "profiles": [
                {
                    "engine": "claude",
                    "name": "work",
                    "config_dir": None,
                    "extra_env": {},
                    "enabled": True,
                    "priority": 100,
                },
                {
                    "engine": "claude",
                    "name": "personal",
                    "config_dir": None,
                    "extra_env": {},
                    "enabled": True,
                    "priority": 10,
                },
            ],
            "supported_engines": ["claude"],
        }
        policy_payload = {
            "policies": [
                {
                    "id": 1,
                    "schedule_id": None,
                    "target_type": "plan_archive_analyze",
                    "engine": "claude",
                    "profile_name": "work",
                    "enabled": False,
                    "priority": 0,
                    "allowed_windows": [],
                    "quiet_windows": [],
                    "created_at": "2026-05-05T21:00:00",
                    "updated_at": "2026-05-05T21:00:00",
                }
            ]
        }

        def handle_api(route):
            url = route.request.url
            method = route.request.method
            calls.append(f"{method} {url}")
            if "/api/v1/llm/bootstrap" in url:
                payload = _llm_bootstrap_payload()
                payload["list"] = {"items": [request], "total": 1, "page": 1, "page_size": 20, "pages": 1}
                _json_response(route, payload)
                return
            if "/api/v1/llm/requests" in url:
                _json_response(route, {"items": [request], "total": 1, "page": 1, "page_size": 20, "pages": 1})
                return
            if "/api/v1/llm/stats" in url:
                _json_response(route, {"total": 1, "pending": 1, "processing": 0, "completed": 0, "failed": 0})
                return
            if "/api/v1/llm/worker/status" in url:
                _json_response(route, {"status": "healthy", "state": "idle", "message": "ready"})
                return
            if "/api/v1/llm/quota-status" in url:
                _json_response(route, {})
                return
            if "/api/v1/llm/profiles/status" in url:
                _json_response(route, [])
                return
            if "/api/v1/llm/profiles" in url:
                _json_response(route, profiles_payload)
                return
            if "/api/v1/llm/schedule-profile-policies" in url:
                _json_response(route, policy_payload)
                return
            if "/api/v1/llm/providers" in url:
                _json_response(route, [{"key": "claude", "display_name": "Claude", "models": []}])
                return
            if "/api/v1/system/liveness" in url:
                _json_response(route, {"status": "ok"})
                return
            _json_response(route, {})

        page.route("**/api/v1/**", handle_api)

        page.goto(f"{frontend_url}/llm", wait_until="domcontentloaded")

        expect(page.get_by_text("스케줄/Profile 정책 차단").first).to_be_visible()
        page.get_by_role("button", name="Profile 정책").click()
        expect(page.get_by_text("Schedule x Profile 정책")).to_be_visible()
        expect(page.get_by_text("plan_archive_analyze").first).to_be_visible()
        page.get_by_role("button", name="정책 추가/갱신").click()
        page.wait_for_timeout(100)

        assert any("GET" in call and "/api/v1/llm/schedule-profile-policies" in call for call in calls)
        assert any("PUT" in call and "/api/v1/llm/schedule-profile-policies" in call for call in calls)


class TestSchedulerRuntime:
    def test_scheduler_page_finishes_loading_without_spinner(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/scheduler")
        _wait_for_runtime_page(page)

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        assert page.get_by_text("해석:").count() > 0, "Scheduler 화면에서 해석 요약이 렌더되지 않았습니다"


class TestSystemSettingsRuntime:
    def test_system_settings_exposes_scheduler_contract(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/system?tab=settings")
        _wait_for_runtime_page(page)
        page.get_by_text("AI 기본값").click()

        _assert_no_loading_spinner(page)
        expect(page.locator("main").first).to_be_visible()
        expect(page.get_by_text("최근 scheduler provider")).to_be_visible()
        expect(page.get_by_text("LLMWorker 기본값")).to_be_visible()
        expect(page.get_by_text("요청값 미지정 시 caller별 기본 provider/model을 적용합니다.")).to_be_visible()
        expect(page.get_by_text("plan_requirements_sync")).to_be_visible()

    def test_ai_profile_settings_exposes_capacity_pool_controls(self, page: Page, frontend_url: str):
        calls: list[str] = []
        _install_profile_pool_routes(page, calls)

        page.goto(f"{frontend_url}/system?tab=settings")
        _wait_for_runtime_page(page)
        page.get_by_text("AI 프로필").click()

        expect(page.get_by_placeholder("프로필 이름 (예: work, personal)").first).to_have_value("work")
        expect(page.locator('input[title="라우팅 우선순위"]').first).to_have_value("100")
        expect(page.get_by_text("paused_by_quota")).to_be_visible()
        expect(page.get_by_role("button", name="재개")).to_be_visible()
        expect(page.get_by_role("button", name="일시중지").first).to_be_visible()
        expect(page.get_by_role("button", name="CLI 실행").first).to_be_visible()

        page.get_by_role("button", name="일시중지").first.click()
        page.wait_for_timeout(100)

        assert any("/api/v1/llm/profiles/status" in call for call in calls)
        assert any("/api/v1/llm/profiles/claude/personal/pause" in call for call in calls)
