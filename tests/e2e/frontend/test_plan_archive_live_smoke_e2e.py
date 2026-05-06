"""[T4: live frontend smoke] route mock 없이 admin frontend 6101에 접속한다."""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

ADMIN_URL = "http://localhost:6101"
LIVE_TEXT_MARKERS = ("archive", "스케줄", "분석", "후보")
ARCHIVE_TAB_MARKERS = ("archive", "retrieval", "sync", "plan-archive", "이 화면")


def _body_excerpt(page: Page) -> str:
    body_text = page.inner_text("body")
    return body_text[:400].replace("\n", " ")


def test_plan_archive_page_live(page: Page) -> None:
    page.goto(f"{ADMIN_URL}/scheduler/plan-archive", wait_until="domcontentloaded")
    expect(page.locator("body")).to_be_visible()

    body_text = page.inner_text("body")
    lowered = body_text.lower()
    assert any(marker in lowered or marker in body_text for marker in LIVE_TEXT_MARKERS), (
        f"plan archive live page did not expose expected text; "
        f"url={page.url}; body={_body_excerpt(page)}"
    )


def test_archivetab_residual_live(page: Page) -> None:
    page.goto(f"{ADMIN_URL}/automation?tab=plans&subtab=archive", wait_until="domcontentloaded")
    expect(page.locator("body")).to_be_visible()

    body_text = page.inner_text("body")
    lowered = body_text.lower()
    assert any(marker in lowered or marker in body_text for marker in ARCHIVE_TAB_MARKERS), (
        f"ArchiveTab residual live page did not expose expected text; "
        f"url={page.url}; body={_body_excerpt(page)}"
    )
    assert "/scheduler/plan-archive" not in page.url, (
        f"ArchiveTab auto-redirected to {page.url}; should stay on residual archive tab"
    )


def test_source_contract_no_route_mock() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "page." + "route("
    assert forbidden not in source


def test_source_contract_has_http_live_marker() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert "pytest.mark.http_live" in source
