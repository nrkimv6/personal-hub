import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _stub_events_page_bootstrap(page: Page) -> None:
    empty_list_payload = '{"items":[],"total":0,"page":1,"page_size":20,"total_pages":0}'
    page.route(
        "**/api/v1/events/deadline-counts**",
        lambda route: route.fulfill(status=200, content_type="application/json", body="{}"),
    )
    page.route(
        "**/api/v1/events?**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=empty_list_payload),
    )


def test_event_import_url_modal_shows_pending_acceptance_message(
    page: Page, frontend_url: str, system_mode: str
):
    _skip_admin_mode_if_public(system_mode)
    _stub_events_page_bootstrap(page)

    page.route(
        "**/api/v1/events/import-from-url",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="""
            {
              "success": true,
              "is_event": true,
              "page_type": "google_forms",
              "extraction_method": "structured",
              "extracted_event": null,
              "created_event": null,
              "request_id": 321,
              "message": "이벤트 등록 요청을 받았습니다 (요청 ID: 321)",
              "error": null
            }
            """,
        ),
    )

    page.goto(f"{frontend_url}/events?tab=online")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="URL 가져오기").click()
    page.get_by_label("이벤트 URL").fill("https://forms.gle/pending321")
    page.get_by_role("button", name="추출").click()

    expect(page.get_by_text("요청 접수")).to_be_visible()
    expect(page.get_by_text("이벤트 등록 요청을 받았습니다 (요청 ID: 321)")).to_be_visible()
    expect(page.get_by_text("요청 ID: 321")).to_be_visible()
    expect(page.get_by_role("link", name="LLM 요청 보기")).to_be_visible()
    expect(page.get_by_role("button", name="추출된 정보 사용")).to_have_count(0)
    expect(page.get_by_role("button", name="그래도 이벤트로 등록")).to_have_count(0)


def test_event_import_url_modal_shows_error_without_pending_panel(
    page: Page, frontend_url: str, system_mode: str
):
    _skip_admin_mode_if_public(system_mode)
    _stub_events_page_bootstrap(page)

    page.route(
        "**/api/v1/events/import-from-url",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="""
            {
              "success": false,
              "is_event": true,
              "page_type": "unknown",
              "extraction_method": "skipped",
              "extracted_event": null,
              "created_event": null,
              "request_id": null,
              "message": null,
              "error": "동일 URL로 등록된 이벤트가 있습니다 (ID: 7)"
            }
            """,
        ),
    )

    page.goto(f"{frontend_url}/events?tab=online")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="URL 가져오기").click()
    page.get_by_label("이벤트 URL").fill("https://forms.gle/duplicate7")
    page.get_by_role("button", name="추출").click()

    expect(page.get_by_text("동일 URL로 등록된 이벤트가 있습니다 (ID: 7)")).to_be_visible()
    expect(page.get_by_text("요청 접수")).to_have_count(0)
    expect(page.get_by_role("link", name="LLM 요청 보기")).to_have_count(0)
