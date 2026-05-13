"""List Board V2 properties/columns/sort live HTTP 통합 TC — admin API (localhost:8001) 기준."""
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import pytest

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"

_IMPORT_MD = (
    "| Course | Duration |\n"
    "|--------|----------|\n"
    "| [HTTP Props Test Alpha](https://example.com/props-http-alpha) | 10 minutes |\n"
    "| [HTTP Props Test Beta](https://example.com/props-http-beta) | 30 minutes |\n"
    "| [HTTP Props Test Gamma](https://example.com/props-http-gamma) | 20 minutes |"
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


def _patch_json(path: str, body: dict, timeout: float = 5.0):
    data = json.dumps(body).encode()
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def _delete_json(path: str, timeout: float = 5.0):
    req = Request(f"{BASE_URL}{path}", method="DELETE")
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode()


def _get_json(path: str, timeout: float = 5.0):
    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def _get_status(path: str, timeout: float = 5.0) -> int:
    try:
        with urlopen(f"{BASE_URL}{path}", timeout=timeout) as resp:
            return resp.status
    except HTTPError as e:
        return e.code


def test_liveness():
    status, payload = _get_json("/api/v1/system/liveness")
    assert status == 200
    assert payload["status"] == "ok"


def test_column_create_and_list():
    """column CRUD: create → list → 확인."""
    # 고유 key 사용 (동시 테스트 격리)
    import time
    ts = int(time.time() * 1000) % 100000
    key = f"http_col_{ts}"

    status, col = _post_json("/api/v1/list-board/columns", {
        "key": key,
        "display_name": "HTTP Test Column",
        "column_type": "checkbox",
    })
    assert status in (200, 201)
    assert col["key"] == key
    assert col["column_type"] == "checkbox"
    col_id = col["id"]

    # list에 포함되는지 확인
    status2, cols = _get_json("/api/v1/list-board/columns")
    assert status2 == 200
    assert isinstance(cols, list)
    keys = [c["key"] for c in cols]
    assert key in keys

    # cleanup
    _delete_json(f"/api/v1/list-board/columns/{col_id}")


def test_column_create_duplicate_key_rejected():
    """중복 key는 409로 거부된다."""
    import time
    ts = int(time.time() * 1000) % 100000
    key = f"dup_key_{ts}"

    status1, _ = _post_json("/api/v1/list-board/columns", {
        "key": key, "display_name": "First", "column_type": "text"
    })
    assert status1 in (200, 201)

    try:
        status2, _ = _post_json("/api/v1/list-board/columns", {
            "key": key, "display_name": "Second", "column_type": "text"
        })
        assert status2 == 409, f"expected 409, got {status2}"
    except HTTPError as e:
        assert e.code == 409

    # cleanup: list에서 id 찾아 삭제
    _, cols = _get_json("/api/v1/list-board/columns")
    for c in cols:
        if c["key"] == key:
            _delete_json(f"/api/v1/list-board/columns/{c['id']}")
            break


def test_properties_patch_shallow_merge():
    """properties PATCH: partial merge — 요청 key만 업데이트, 나머지 보존."""
    import time
    ts = int(time.time() * 1000) % 100000
    key1 = f"p_done_{ts}"
    key2 = f"p_tag_{ts}"

    # column 두 개 생성
    _, c1 = _post_json("/api/v1/list-board/columns", {
        "key": key1, "display_name": "Done", "column_type": "checkbox"
    })
    _, c2 = _post_json("/api/v1/list-board/columns", {
        "key": key2, "display_name": "Tag", "column_type": "select", "options": ["A", "B", "C"]
    })

    # item import
    src = f"http-props-{ts}"
    _post_json("/api/v1/list-board/import", {"markdown_text": _IMPORT_MD, "source": src})

    # item 조회
    _, resp = _get_json(f"/api/v1/list-board/items?source={src}")
    items = resp.get("items", [])
    assert len(items) > 0
    alpha = next((i for i in items if "Alpha" in i["title"]), items[0])
    item_id = alpha["id"]

    # 첫 번째 patch: done=True, tag="A"
    status, updated = _patch_json(
        f"/api/v1/list-board/items/{item_id}/properties",
        {"properties": {key1: True, key2: "A"}},
    )
    assert status == 200
    assert updated["properties"][key1] is True
    assert updated["properties"][key2] == "A"

    # 두 번째 patch: done만 False로 — tag는 그대로여야 함
    status2, updated2 = _patch_json(
        f"/api/v1/list-board/items/{item_id}/properties",
        {"properties": {key1: False}},
    )
    assert status2 == 200
    assert updated2["properties"][key1] is False
    assert updated2["properties"].get(key2) == "A", "overwrite-block: tag must be preserved"

    # cleanup
    _delete_json(f"/api/v1/list-board/columns/{c1['id']}")
    _delete_json(f"/api/v1/list-board/columns/{c2['id']}")


def test_sort_by_system_column():
    """sort_by=title&sort_order=asc HTTP 검증."""
    import time
    ts = int(time.time() * 1000) % 100000
    src = f"http-sort-{ts}"
    _post_json("/api/v1/list-board/import", {"markdown_text": _IMPORT_MD, "source": src})

    status, resp = _get_json(f"/api/v1/list-board/items?source={src}&sort_by=title&sort_order=asc")
    assert status == 200
    titles = [i["title"] for i in resp["items"]]
    assert titles == sorted(titles), f"asc sort failed: {titles}"

    status2, resp2 = _get_json(f"/api/v1/list-board/items?source={src}&sort_by=title&sort_order=desc")
    assert status2 == 200
    titles_desc = [i["title"] for i in resp2["items"]]
    assert titles_desc == sorted(titles_desc, reverse=True)


def test_sort_by_invalid_key_falls_back():
    """허용되지 않은 sort_by는 400 또는 기본 정렬로 안전 처리."""
    import time
    ts = int(time.time() * 1000) % 100000
    src = f"http-sort-invalid-{ts}"
    _post_json("/api/v1/list-board/import", {"markdown_text": _IMPORT_MD, "source": src})

    status = _get_status(f"/api/v1/list-board/items?source={src}&sort_by=__evil__injection&sort_order=asc")
    assert status in (200, 400), f"unexpected status {status} for invalid sort key"


def test_sources_endpoint():
    """GET /api/v1/list-board/sources 응답 스키마 검증."""
    import time
    ts = int(time.time() * 1000) % 100000
    src = f"http-sources-{ts}"
    _post_json("/api/v1/list-board/import", {"markdown_text": _IMPORT_MD, "source": src})

    status, resp = _get_json("/api/v1/list-board/sources")
    assert status == 200
    assert isinstance(resp, list)
    # 방금 import한 source가 포함돼야 함
    source_names = [s["source"] for s in resp]
    assert src in source_names
    # 각 항목에 count와 last_import_at 포함
    our_src = next(s for s in resp if s["source"] == src)
    assert "count" in our_src
    assert "last_import_at" in our_src
