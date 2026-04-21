"""system orphan-cleanup HTTP 통합 테스트."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"

from app.main import app
from app.routes import system as system_mod


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_system_orphan_cleanup_http_wires_detector_and_returns_counts(client):
    """POST /system/orphan-cleanup가 detector scan/cleanup 결과를 그대로 반환한다."""
    fake_detector = MagicMock()
    fake_detector.scan = AsyncMock(
        return_value=[{"pid": "1111"}, {"pid": "2222"}]
    )
    fake_detector.cleanup = AsyncMock(return_value=[{"pid": "1111"}])

    with patch(
        "app.shared.redis.client.RedisClient.get_client",
        new=AsyncMock(return_value=object()),
    ), \
        patch("app.shared.process.registry.ProcessRegistry", return_value=MagicMock()) as mock_registry, \
        patch(
            "app.shared.process.orphan_detector.OrphanDetector",
            return_value=fake_detector,
        ) as mock_detector:
        resp = client.post("/api/v1/system/orphan-cleanup")

    assert resp.status_code == 200
    assert resp.json() == {
        "orphans_found": 2,
        "cleaned": 1,
        "details": [{"pid": "1111"}],
    }
    mock_detector.assert_called_once_with(
        mock_registry.return_value,
        repo_root=Path(system_mod.__file__).resolve().parents[2],
    )
    fake_detector.scan.assert_awaited_once_with()
    fake_detector.cleanup.assert_awaited_once_with(
        [{"pid": "1111"}, {"pid": "2222"}],
        force=True,
    )


def test_system_orphan_cleanup_http_returns_503_when_redis_unavailable(client):
    """Redis가 없으면 orphan cleanup API는 503으로 거절해야 한다."""
    with patch(
        "app.shared.redis.client.RedisClient.get_client",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post("/api/v1/system/orphan-cleanup")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Redis not available"
