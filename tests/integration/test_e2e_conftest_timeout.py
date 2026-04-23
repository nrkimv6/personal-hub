"""Integration TC: 3초 지연 응답 서버로 timeout=5 root cause를 재현한다.

timeout=2였다면 URLError로 실패했을 조건(3초 지연)을 timeout=5에서 통과함을 검증한다.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.e2e.conftest import _assert_frontend_available, system_mode

_SYSTEM_MODE_FN = getattr(system_mode, "__wrapped__", system_mode)

_DELAY_SECONDS = 3  # timeout=2에서는 실패, timeout=5에서는 통과하는 지연


class _DelayedModeHandler(BaseHTTPRequestHandler):
    """3초 지연 후 {"mode": "admin"} 을 반환하는 핸들러."""

    def do_GET(self):
        time.sleep(_DELAY_SECONDS)
        body = json.dumps({"mode": "admin"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class _DelayedFrontendHandler(BaseHTTPRequestHandler):
    """3초 지연 후 200 OK를 반환하는 핸들러."""

    def do_GET(self):
        time.sleep(_DELAY_SECONDS)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_):
        pass


def _start_server(handler_cls) -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


@pytest.mark.integration
class TestSystemModeIntegrationTimeout:
    def test_system_mode_integration_waits_for_delayed_mode_response(self):
        """root cause 재현: 3초 지연 응답이 timeout=5에서 통과한다.

        동일 조건(3초 지연)은 timeout=2에서는 URLError로 실패했을 것이다.
        """
        server, port = _start_server(_DelayedModeHandler)
        try:
            result = _SYSTEM_MODE_FN(f"http://127.0.0.1:{port}")
            assert result == "admin"
        finally:
            server.shutdown()

    def test_frontend_available_integration_waits_for_delayed_frontend_response(self):
        """root cause 재현: 3초 지연 frontend 응답이 timeout=5에서 통과한다."""
        server, port = _start_server(_DelayedFrontendHandler)
        try:
            _assert_frontend_available(f"http://127.0.0.1:{port}")
        finally:
            server.shutdown()
