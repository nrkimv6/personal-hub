import os
import re
import time
import uuid
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect


pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

ADMIN_API = os.environ.get("MONITOR_ADMIN_API_BASE") or os.environ.get("E2E_API_URL", "http://localhost:8001")


def _evidence_dir() -> Path:
    root = Path(os.environ.get("TEMP", "."))
    path = root / "codex" / "monitor-page" / "book-whisperer" / "e2e"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _create_book(overrides: dict[str, object] | None = None) -> dict[str, object]:
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    payload = {
        "isbn": f"codex-e2e-{suffix}",
        "title": f"Book Whisperer E2E {suffix}",
        "author": "Codex Browser",
        "publisher": "Monitor Page",
        "category": "검증",
        "condition": "good",
        "location": "e2e-shelf",
        "reread_intent": 4,
        "accessibility_library": "yes",
        "accessibility_millie": "no",
        "accessibility_ebook": "check",
        "accessibility_used_buyback": "yes",
        "used_buyback_price": 1500,
        "recommendation": "sell",
        "disposal": "undecided",
    }
    if overrides:
        payload.update(overrides)
    with httpx.Client(base_url=ADMIN_API, timeout=10.0) as client:
        liveness = client.get("/api/v1/system/liveness")
        if liveness.status_code != 200:
            pytest.skip(f"Admin API liveness unavailable: {liveness.status_code} {liveness.text}")
        response = client.post("/api/v1/books", json=payload)
        if response.status_code in (401, 403):
            pytest.skip(f"Admin auth rejected request: {response.status_code}")
        assert response.status_code == 201, response.text
        return response.json()


def _delete_book(book_id: int) -> None:
    with httpx.Client(base_url=ADMIN_API, timeout=10.0) as client:
        client.delete(f"/api/v1/books/{book_id}")


def test_personal_books_page_renders_live_book_and_filter_actions(page: Page, frontend_url: str):
    book = _create_book()
    try:
        page.goto(f"{frontend_url}/personal/books", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="전체 도서")).to_be_visible()

        search = page.get_by_placeholder("제목 · 저자 · ISBN으로 검색")
        search.fill(str(book["title"]))

        title = page.get_by_role("link", name=re.compile(re.escape(str(book["title"])))).first
        expect(title).to_be_visible()
        expect(title).to_contain_text("Codex Browser")

        page.get_by_role("button", name=re.compile("미정")).first.click(force=True)
        expect(title).to_be_visible()

        page.get_by_role("button", name="도서관 O").click()
        expect(title).to_be_visible()
        expect(page.get_by_text("해당 조건의 책이 없습니다")).not_to_be_visible()

        evidence = _evidence_dir()
        page.screenshot(path=str(evidence / "personal-books-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{frontend_url}/personal/books", wait_until="domcontentloaded")
        page.get_by_placeholder("제목 · 저자 · ISBN으로 검색").fill(str(book["title"]))
        expect(page.get_by_role("link", name=re.compile(re.escape(str(book["title"])))).first).to_be_visible()
        page.screenshot(path=str(evidence / "personal-books-mobile.png"), full_page=True)
    finally:
        _delete_book(int(book["id"]))


def test_personal_books_detail_navigation_shows_highlight_protection(page: Page, frontend_url: str):
    book = _create_book(
        {
            "highlights": [
                {
                    "page": 12,
                    "quote": "Representative rendered marker for detail protection",
                    "tags": ["e2e"],
                    "importance": 4,
                }
            ]
        }
    )
    try:
        page.goto(f"{frontend_url}/personal/books/{book['id']}", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name=str(book["title"]))).to_be_visible()
        expect(page.get_by_text(f"ISBN {book['isbn']}")).to_be_visible()
        expect(page.get_by_text("추천 매입가")).to_be_visible()
        expect(page.get_by_text("알라딘", exact=True)).to_be_visible()
        expect(page.get_by_text("최상")).to_be_visible()
        expect(page.get_by_text("상", exact=True)).to_be_visible()
        expect(page.get_by_text("중", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="알라딘 매입가 확인")).to_be_visible()
        expect(page.get_by_text("Representative rendered marker for detail protection")).to_be_visible()

        page.get_by_role("button", name="판매").click()
        expect(page.get_by_text("하이라이트가 1개 있습니다")).to_be_visible()
        expect(page.get_by_role("button", name="계속")).to_be_visible()
    finally:
        _delete_book(int(book["id"]))


def test_personal_books_scan_mock_scanner_state_transition(page: Page, frontend_url: str):
    page.goto(f"{frontend_url}/personal/books/scan", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="ISBN 바코드 등록")).to_be_visible()
    expect(page.get_by_text("ISBN 바코드를 사각형 안에 비춰주세요")).to_be_visible()

    page.get_by_role("button", name="스캔 시작").click()
    expect(page.get_by_text("스캔 중...").first).to_be_visible()
    expect(page.get_by_text(re.compile(r"ISBN 978"))).to_be_visible(timeout=3000)
    expect(page.get_by_role("button", name="다시 스캔")).to_be_visible()
