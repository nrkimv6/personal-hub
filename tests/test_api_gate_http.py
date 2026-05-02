import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

pytestmark = pytest.mark.http_live


def _frontend_url() -> str:
    return os.environ.get("E2E_FRONTEND_URL", "http://localhost:6101").rstrip("/")


def _json_request(path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{_frontend_url()}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        return exc.code, parsed


def test_gate_status_returns_open_by_default():
    _json_request("/__local/api-gate/open", method="POST", payload={"reason": "http setup"})

    status, body = _json_request("/__local/api-gate/status")

    assert status == 200
    assert body["state"] == "open"


def test_gate_close_returns_200():
    _json_request("/__local/api-gate/open", method="POST", payload={"reason": "http setup"})

    status, body = _json_request(
        "/__local/api-gate/close",
        method="POST",
        payload={"api_port": 8001, "reason": "test"},
    )

    assert status == 200
    assert body["success"] is True


def test_gate_close_then_status_returns_closed():
    _json_request("/__local/api-gate/open", method="POST", payload={"reason": "http setup"})
    _json_request(
        "/__local/api-gate/close",
        method="POST",
        payload={"api_port": 8001, "reason": "test"},
    )

    status, body = _json_request("/__local/api-gate/status")

    assert status == 200
    assert body["state"] in {"closed", "recovering"}


def test_gate_open_returns_200():
    status, body = _json_request("/__local/api-gate/open", method="POST", payload={"reason": "test"})

    assert status == 200
    assert body["success"] is True
    assert body["gate"]["state"] == "open"


def test_gate_close_missing_api_port_returns_400():
    status, body = _json_request(
        "/__local/api-gate/close",
        method="POST",
        payload={"reason": "missing"},
    )

    assert status == 400
    assert body["code"] == "invalid_api_port"


def test_gate_close_invalid_api_port_returns_400():
    status, body = _json_request(
        "/__local/api-gate/close",
        method="POST",
        payload={"api_port": 9999, "reason": "invalid"},
    )

    assert status == 400
    assert body["code"] == "invalid_api_port"
