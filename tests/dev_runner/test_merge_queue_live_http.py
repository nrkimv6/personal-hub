"""Live HTTP smoke tests for merge queue read endpoints.

Run in /merge-test with:
    python -m pytest -o addopts="--capture=sys" tests/dev_runner/test_merge_queue_live_http.py -m http_live -v
"""

import httpx
import pytest

from tests.dev_runner.live_http_readiness import ADMIN_BASE_URL, wait_until_live_api_ready

pytestmark = pytest.mark.http_live


def test_merge_queue_live_right_returns_list_without_sse():
    wait_until_live_api_ready()

    response = httpx.get(
        f"{ADMIN_BASE_URL}/api/v1/dev-runner/merge-queue",
        timeout=5,
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert "text/event-stream" not in response.headers.get("content-type", "")


def test_merge_queue_length_live_right_returns_length():
    wait_until_live_api_ready()

    response = httpx.get(
        f"{ADMIN_BASE_URL}/api/v1/dev-runner/merge-queue-length",
        timeout=5,
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("length"), int)
