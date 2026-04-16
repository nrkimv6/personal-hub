"""Events page visibility regression tests."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_events_filter_can_request_ongoing_or_upcoming(page: Page, frontend_url: str):
    seen_event_statuses: list[str | None] = []

    def handle_events(route):
        request = route.request
        seen_event_statuses.append(request.url.split("event_status=")[1].split("&")[0] if "event_status=" in request.url else None)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"items":[],"total":0,"page":1,"page_size":20,"total_pages":0}',
        )

    page.route("**/api/v1/events/deadline-counts**", lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
    page.route("**/api/v1/events?**", handle_events)

    page.goto(f"{frontend_url}/events?tab=online")
    page.wait_for_load_state("networkidle")

    filter_button = page.get_by_role("button", name="진행+예정").first
    expect(filter_button).to_be_visible()
    filter_button.click()
    page.wait_for_load_state("networkidle")

    assert "ongoing_or_upcoming" in seen_event_statuses
