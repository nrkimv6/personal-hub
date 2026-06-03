import os
import time
import uuid

import httpx
import pytest


pytestmark = pytest.mark.http_live

ADMIN_API = os.environ.get("MONITOR_ADMIN_API_BASE") or os.environ.get("E2E_API_URL", "http://localhost:8001")


def _client() -> httpx.Client:
    return httpx.Client(base_url=ADMIN_API, timeout=10.0)


def _book_payload() -> dict[str, object]:
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return {
        "isbn": f"codex-http-{suffix}",
        "title": f"Book Whisperer HTTP {suffix}",
        "author": "Codex Live",
        "publisher": "Monitor Page",
        "category": "검증",
        "condition": "good",
        "location": "live-test-shelf",
        "reread_intent": 3,
        "accessibility_library": "yes",
        "accessibility_millie": "check",
        "accessibility_ebook": "check",
        "accessibility_used_buyback": "yes",
        "used_buyback_price": 1200,
        "recommendation": "sell",
        "disposal": "undecided",
    }


def test_books_http_live_create_update_highlight_delete_flow():
    with _client() as client:
        liveness = client.get("/api/v1/system/liveness")
        if liveness.status_code != 200:
            pytest.skip(f"Admin API liveness unavailable: {liveness.status_code} {liveness.text}")

        payload = _book_payload()
        created = client.post("/api/v1/books", json=payload)
        assert created.status_code == 201, created.text
        book = created.json()
        book_id = book["id"]

        try:
            assert book["title"] == payload["title"]
            assert book["disposal"] == "undecided"

            listed = client.get("/api/v1/books", params={"search": payload["isbn"], "limit": 10})
            assert listed.status_code == 200, listed.text
            assert any(item["id"] == book_id for item in listed.json()["items"])

            patched = client.patch(
                f"/api/v1/books/{book_id}",
                json={"disposal": "sell", "sell_status": "ready", "review_date": "2099-01-01"},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["disposal"] == "sell"
            assert patched.json()["sell_status"] == "ready"

            highlight = client.post(
                f"/api/v1/books/{book_id}/highlights",
                json={"page": 42, "quote": "Live HTTP highlight marker", "tags": ["live"], "importance": 4},
            )
            assert highlight.status_code == 201, highlight.text
            assert highlight.json()["quote"] == "Live HTTP highlight marker"

            highlights = client.get(f"/api/v1/books/{book_id}/highlights")
            assert highlights.status_code == 200, highlights.text
            assert any(item["quote"] == "Live HTTP highlight marker" for item in highlights.json())
        finally:
            deleted = client.delete(f"/api/v1/books/{book_id}")
            assert deleted.status_code in (200, 404), deleted.text
