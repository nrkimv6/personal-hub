import json
import time
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.http_live

BASE_URL = "http://localhost:8001"


def _get_json(path: str, timeout: float = 3.0) -> tuple[int, dict, float]:
    started = time.perf_counter()
    with urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        elapsed = time.perf_counter() - started
        return response.status, json.loads(response.read().decode("utf-8")), elapsed


def test_liveness_is_available_for_live_contract_gate():
    status, payload, elapsed = _get_json("/api/v1/system/liveness")

    assert status == 200
    assert payload["status"] == "ok"
    assert elapsed < 5.0


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/worker/commands/live-missing-command",
        "/api/v1/system/services/commands/live-missing-command",
        "/api/v1/dev-runner/commands/live-missing-command",
    ],
)
def test_command_status_endpoints_return_pending_without_blocking(path: str):
    status, payload, elapsed = _get_json(path)

    assert status == 200
    assert payload["status"] == "pending"
    assert payload["command_id"] == "live-missing-command"
    assert elapsed < 5.0


def test_image_pdf_health_is_fast_read_contract():
    status, payload, elapsed = _get_json("/api/v1/image-pdf/health")

    assert status == 200
    assert isinstance(payload["supported_extensions"], list)
    assert elapsed < 5.0
