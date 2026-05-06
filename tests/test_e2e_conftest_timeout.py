"""Unit TC: tests.e2e.conftest system_mode / _assert_frontend_available timeout=5 검증."""
from __future__ import annotations

from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from tests.e2e.conftest import _assert_frontend_available, system_mode

# system_mode는 @pytest.fixture 래퍼이므로 __wrapped__로 원본 함수에 접근한다.
_SYSTEM_MODE_FN = getattr(system_mode, "__wrapped__", system_mode)


class _Response:
    """urlopen mock용 최소 HTTP 응답 객체."""

    def __init__(self, payload: bytes = b'{"mode": "admin"}'):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_) -> bool:
        return False


# ---------------------------------------------------------------------------
# system_mode fixture
# ---------------------------------------------------------------------------


class TestSystemModeTimeout:
    def test_system_mode_right_returns_payload_and_uses_timeout_5(self):
        """R: timeout=5로 urlopen을 호출하고 mode 값을 반환한다."""
        captured: dict = {}

        def fake_urlopen(url: str, timeout: int) -> _Response:
            captured["timeout"] = timeout
            return _Response(b'{"mode": "admin"}')

        with patch("tests.e2e.conftest.urlopen", fake_urlopen):
            result = _SYSTEM_MODE_FN("http://localhost:8001")

        assert result == "admin"
        assert captured["timeout"] == 5

    def test_system_mode_boundary_defaults_public_when_mode_missing_and_uses_timeout_5(self):
        """B: mode 키가 없으면 'public' 기본값을 반환하고 timeout=5를 사용한다."""
        captured: dict = {}

        def fake_urlopen(url: str, timeout: int) -> _Response:
            captured["timeout"] = timeout
            return _Response(b"{}")

        with patch("tests.e2e.conftest.urlopen", fake_urlopen):
            result = _SYSTEM_MODE_FN("http://localhost:8001")

        assert result == "public"
        assert captured["timeout"] == 5

    def test_system_mode_error_fail_fast_on_http_error(self):
        """E: URLError 발생 시 pytest.fail()로 테스트를 즉시 중단한다."""

        def fake_urlopen(url: str, timeout: int) -> None:
            raise URLError("Connection refused")

        with patch("tests.e2e.conftest.urlopen", fake_urlopen):
            with pytest.raises(pytest.fail.Exception):
                _SYSTEM_MODE_FN("http://localhost:8001")


# ---------------------------------------------------------------------------
# _assert_frontend_available helper
# ---------------------------------------------------------------------------


class TestFrontendAvailableTimeout:
    def test_frontend_available_right_uses_timeout_5(self):
        """R: timeout=5로 urlopen을 호출하고 정상 응답이면 예외 없이 반환한다."""
        captured: dict = {}

        def fake_urlopen(url: str, timeout: int) -> _Response:
            captured["timeout"] = timeout
            return _Response(b"<html/>")

        with patch("tests.e2e.conftest.urlopen", fake_urlopen):
            _assert_frontend_available("http://localhost:6101")

        assert captured["timeout"] == 5

    def test_frontend_available_error_fail_fast_on_urlerror(self):
        """E: URLError 발생 시 pytest.fail()로 테스트를 즉시 중단한다."""

        def fake_urlopen(url: str, timeout: int) -> None:
            raise URLError("Connection refused")

        with patch("tests.e2e.conftest.urlopen", fake_urlopen):
            with pytest.raises(pytest.fail.Exception):
                _assert_frontend_available("http://localhost:6101")
