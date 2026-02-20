"""
Everything HTTP API 서비스 단위 테스트

Right-BICEP / CORRECT 패턴:
- Right:       일반/regex/확장자/경로 검색 결과 반환
- Boundary:    빈 쿼리, 특수문자, max=0
- Error:       ConnectError, ReadTimeout, 잘못된 JSON
- CORRECT-Conformance: .py vs py 확장자 둘 다 수용
- CORRECT-Range:       max_results 범위 처리
- CORRECT-Existence:   빈 extensions, 빈 paths
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.file_search.services.everything import EverythingService


# ── helpers ───────────────────────────────────────────────────────────────

def _mock_httpx_response(json_data: dict, status_code: int = 200):
    """httpx 응답 Mock 생성."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class FakeAsyncClient:
    """httpx.AsyncClient context manager Mock."""
    def __init__(self, response=None, side_effect=None):
        self._response = response
        self._side_effect = side_effect

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, *args, **kwargs):
        if self._side_effect:
            raise self._side_effect
        return self._response


# ── Right: 정상 동작 ─────────────────────────────────────────────────────

class TestEverythingRight:
    """Right — 올바른 결과를 반환하는지 검증."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, everything_json_single):
        """Right: 일반 검색어로 결과 1건 반환."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_single)

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(response=resp)):
            results = await svc.search("routes")

        assert len(results) == 1
        assert results[0]["file_name"] == "routes.py"
        assert "D:\\work\\project\\app" in results[0]["file_path"]

    @pytest.mark.asyncio
    async def test_search_regex_prefix_in_query(self, everything_json_single):
        """Right: regex=True 이면 쿼리에 'regex:' 접두사 포함."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_single)

        captured_params = {}

        async def fake_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return resp

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(side_effect=fake_get)

        with patch("httpx.AsyncClient", return_value=fake_client):
            await svc.search("test.py", regex=True)

        assert captured_params.get("s", "").startswith("regex:")

    @pytest.mark.asyncio
    async def test_search_extension_filter_syntax(self, everything_json_multi):
        """Right: 확장자 필터가 'ext:py;ts' 형식으로 포함됨."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_multi)

        captured_params = {}

        async def fake_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return resp

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(side_effect=fake_get)

        with patch("httpx.AsyncClient", return_value=fake_client):
            await svc.search("search", extensions=["py", "ts"])

        query = captured_params.get("s", "")
        assert "ext:py;ts" in query

    @pytest.mark.asyncio
    async def test_search_path_filter_syntax(self, everything_json_single):
        """Right: 경로 필터가 'path:D:\\work' 형식으로 포함됨."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_single)

        captured_params = {}

        async def fake_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return resp

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(side_effect=fake_get)

        with patch("httpx.AsyncClient", return_value=fake_client):
            await svc.search("foo", paths=["D:\\work"])

        query = captured_params.get("s", "")
        assert "path:D:\\work" in query


# ── Boundary: 경계값 ─────────────────────────────────────────────────────

class TestEverythingBoundary:
    """Boundary — 경계 조건 테스트."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        """Boundary: 빈 쿼리 → HTTP 요청 없이 빈 결과."""
        svc = EverythingService()
        # httpx가 호출되지 않아야 하므로 patch 없이도 통과해야 함
        results = await svc.search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_special_chars_in_query(self, everything_json_empty):
        """Boundary: 특수문자 쿼리도 오류 없이 처리."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_empty)

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(response=resp)):
            results = await svc.search("*.py [brackets] foo\\bar")

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_max_results_zero_returns_empty(self, everything_json_empty):
        """CORRECT-Range: max_results=0 → 결과 없음 (빈 리스트)."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_empty)

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(response=resp)):
            results = await svc.search("test", max_results=0)

        assert results == []

    @pytest.mark.asyncio
    async def test_extension_with_dot_prefix(self, everything_json_single):
        """CORRECT-Conformance: '.py' (점 포함) 확장자도 'py'로 정규화."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_single)

        captured_params = {}

        async def fake_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return resp

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(side_effect=fake_get)

        with patch("httpx.AsyncClient", return_value=fake_client):
            await svc.search("foo", extensions=[".py", ".ts"])

        query = captured_params.get("s", "")
        # 점이 제거되어야 함
        assert "ext:py;ts" in query
        assert "ext:.py;.ts" not in query

    @pytest.mark.asyncio
    async def test_empty_extensions_no_ext_filter(self, everything_json_single):
        """CORRECT-Existence: 확장자 미지정 → ext: 필터 없음."""
        svc = EverythingService()
        resp = _mock_httpx_response(everything_json_single)

        captured_params = {}

        async def fake_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return resp

        fake_client = AsyncMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.get = AsyncMock(side_effect=fake_get)

        with patch("httpx.AsyncClient", return_value=fake_client):
            await svc.search("foo")

        query = captured_params.get("s", "")
        assert "ext:" not in query


# ── Error: 에러 처리 ─────────────────────────────────────────────────────

class TestEverythingError:
    """Error — 에러 조건 처리 검증."""

    @pytest.mark.asyncio
    async def test_connect_error_returns_empty(self):
        """Error: ConnectError(서버 다운) → 빈 리스트 반환 (예외 전파 안 함)."""
        svc = EverythingService()

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(side_effect=httpx.ConnectError("연결 실패"))):
            results = await svc.search("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_read_timeout_returns_empty(self):
        """Error: ReadTimeout → 빈 리스트 반환."""
        svc = EverythingService()

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(side_effect=httpx.ReadTimeout("타임아웃"))):
            results = await svc.search("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_invalid_json_response_returns_empty(self):
        """Error: 잘못된 JSON 응답 → 빈 리스트 반환."""
        svc = EverythingService()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("JSON decode error")

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(response=resp)):
            results = await svc.search("test")

        assert results == []

    @pytest.mark.asyncio
    async def test_is_available_connect_error(self):
        """Error: is_available() — 서버 다운 → (False, message)."""
        svc = EverythingService()

        with patch("httpx.AsyncClient", return_value=FakeAsyncClient(side_effect=httpx.ConnectError("연결 실패"))):
            ok, msg = await svc.is_available()

        assert ok is False
        assert "연결 실패" in msg or "포트" in msg


# ── _build_query 단위 테스트 ────────────────────────────────────────────

class TestBuildQuery:
    """_build_query 메서드 단위 검증."""

    def test_plain_query(self):
        svc = EverythingService()
        q = svc._build_query("hello", False, [], [], [])
        assert q == "hello"

    def test_regex_prefix(self):
        svc = EverythingService()
        q = svc._build_query("test.*py", True, [], [], [])
        assert q.startswith("regex:test.*py")

    def test_extensions_joined_semicolon(self):
        svc = EverythingService()
        q = svc._build_query("foo", False, ["py", "ts", "js"], [], [])
        assert "ext:py;ts;js" in q

    def test_excludes_prefixed_exclamation(self):
        svc = EverythingService()
        q = svc._build_query("foo", False, [], [], ["node_modules", "__pycache__"])
        assert "!node_modules" in q
        assert "!__pycache__" in q

    def test_combined_query(self):
        svc = EverythingService()
        q = svc._build_query("test", False, ["py"], ["D:\\work"], ["__pycache__"])
        assert "test" in q
        assert "ext:py" in q
        assert "path:D:\\work" in q
        assert "!__pycache__" in q
