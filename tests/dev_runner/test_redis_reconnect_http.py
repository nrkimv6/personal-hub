"""T5: SSE 엔드포인트 Redis 재연결 HTTP 통합 테스트

TestClient 기반 — 실서버 불필요.
SSE 스트림 첫 이벤트가 `event: connected / data: ok`인지 검증 (기본 동작 유지 확인).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http


def _parse_sse_events(content: str) -> list[dict]:
    """SSE 응답 텍스트를 이벤트 목록으로 파싱."""
    events = []
    current: dict = {}
    for line in content.splitlines():
        if not line:
            if current:
                events.append(current)
                current = {}
        elif line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current["data"] = line[5:].strip()
        elif line.startswith(":"):
            pass  # heartbeat/comment
    if current:
        events.append(current)
    return events


def _mock_log_service_for_connected():
    """초기 connected 이벤트만 보내고 종료하는 LogService mock."""
    from unittest.mock import patch as _patch
    import asyncio

    async def _fake_stream_log_file(self, runner_id, since_line=0):
        yield "event: connected\ndata: ok\n\n"
        yield "event: completed\ndata: completed\n\n"

    async def _fake_stream_merge_log(self, runner_id):
        yield "event: connected\ndata: ok\n\n"
        yield "event: completed\ndata: completed\n\n"

    return (
        _patch(
            "app.modules.dev_runner.services.log_service.LogService.stream_log_file",
            new=_fake_stream_log_file,
        ),
        _patch(
            "app.modules.dev_runner.services.log_service.LogService.stream_merge_log",
            new=_fake_stream_merge_log,
        ),
    )


@pytest.mark.http
class TestLogStreamConnectedEvent:
    """T5: SSE 스트림 초기 connected 이벤트 검증 (기본 동작 유지)"""

    def test_log_stream_returns_connected_event_on_start(self):
        """GET /logs/stream → 첫 이벤트가 event: connected / data: ok"""
        patch_log, _ = _mock_log_service_for_connected()
        with patch_log:
            from app.main import app
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/api/v1/dev-runner/logs/stream",
                    params={"runner_id": "t5-test-runner"},
                    headers={"Accept": "text/event-stream"},
                )
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        assert events, "SSE 이벤트가 없음"
        first = events[0]
        assert first.get("event") == "connected", \
            f"첫 이벤트가 connected가 아님: {first}"
        assert first.get("data") == "ok", \
            f"connected data가 ok가 아님: {first}"

    def test_merge_log_stream_returns_connected_event_on_start(self):
        """GET /merge-log/stream → 첫 이벤트가 event: connected / data: ok"""
        _, patch_merge = _mock_log_service_for_connected()
        with patch_merge:
            from app.main import app
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/api/v1/dev-runner/merge-log/stream",
                    params={"runner_id": "t5-test-runner"},
                    headers={"Accept": "text/event-stream"},
                )
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        assert events, "SSE 이벤트가 없음"
        first = events[0]
        assert first.get("event") == "connected", \
            f"첫 이벤트가 connected가 아님: {first}"
        assert first.get("data") == "ok", \
            f"connected data가 ok가 아님: {first}"
