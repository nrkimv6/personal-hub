import socket
import threading
import time

import pytest

from scripts.fixes.frontend_placeholder import PlaceholderServer

_TEST_PORT = 16302


def _find_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestPlaceholderServerStop:
    def test_stop_completes_within_timeout(self):
        port = _find_free_port()
        server = PlaceholderServer(port)
        server.start()
        time.sleep(0.1)

        start = time.monotonic()
        server.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 3.5, f"stop() took {elapsed:.2f}s — expected < 3.5s"

    def test_stop_with_active_connection(self):
        """active 소켓 연결이 있어도 stop()이 hang 없이 반환되어야 한다."""
        port = _find_free_port()
        server = PlaceholderServer(port)
        server.start()
        time.sleep(0.1)

        # 연결만 맺고 응답을 읽지 않는 소켓으로 브라우저 탭을 모사
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", port))
        sock.send(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n")

        start = time.monotonic()
        server.stop()
        elapsed = time.monotonic() - start

        sock.close()
        assert elapsed < 3.5, f"stop() with active connection took {elapsed:.2f}s — expected < 3.5s"

    def test_stop_idempotent(self):
        port = _find_free_port()
        server = PlaceholderServer(port)
        server.start()
        time.sleep(0.1)

        server.stop()
        server.stop()  # 두 번째 호출 — 예외 없이 완료해야 함
