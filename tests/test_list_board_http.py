"""List Board API live HTTP 통합 TC — admin API (localhost:8001) 기준."""
import json
from urllib.request import urlopen, Request
from urllib.error import URLError

import pytest

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"

_IMPORT_MD = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [HTTP Test Course A](https://example.com/http-test-a) | 10 minutes |\n"
    "| [HTTP Test Course B](https://example.com/http-test-b) | 20 minutes |"
)


def _post_json(path: str, body: dict, timeout: float = 5.0):
    data = json.dumps(body).encode()
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def _get_json(path: str, timeout: float = 5.0):
    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_liveness_before_list_board_tests():
    status, payload = _get_json("/api/v1/system/liveness")
    assert status == 200
    assert payload["status"] == "ok"


def test_import_endpoint_returns_result_schema():
    status, data = _post_json(
        "/api/v1/list-board/import",
        {"markdown_text": _IMPORT_MD, "source": "http-live-test"},
    )
    assert status == 200
    assert "created" in data
    assert "updated" in data
    assert "skipped" in data
    assert "errors" in data


def test_list_items_endpoint_returns_items():
    # import 먼저
    _post_json(
        "/api/v1/list-board/import",
        {"markdown_text": _IMPORT_MD, "source": "http-live-list-test"},
    )
    status, data = _get_json("/api/v1/list-board/items?source=http-live-list-test")
    assert status == 200
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1


def test_upsert_does_not_duplicate_rows():
    source = "http-live-upsert-test"
    _post_json(
        "/api/v1/list-board/import",
        {"markdown_text": _IMPORT_MD, "source": source},
    )
    _, r2 = _post_json(
        "/api/v1/list-board/import",
        {"markdown_text": _IMPORT_MD, "source": source},
    )
    _, list_data = _get_json(f"/api/v1/list-board/items?source={source}")
    # 같은 URL을 두 번 import해도 아이템 수는 2 (중복 없음)
    assert list_data["total"] == 2
    assert r2["created"] == 0
    assert r2["updated"] == 2
