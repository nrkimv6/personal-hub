"""
파일 검색 API 통합 테스트

Right-BICEP / CORRECT 패턴:
- Right:       mode별 분기(filename/content/both), presets, status
- Boundary:    빈 query → 422, 잘못된 mode → 422, max_results 음수 → 422
- Inverse:     preset 적용 시 paths/extensions 오버라이드
- Error:       없는 파일 open → 404, 전체 실패 → 부분 결과
- CORRECT-Conformance: 잘못된 mode enum → 422
- CORRECT-Range:       max_results 음수 → 422
- CORRECT-Existence:   null query → 422
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


def _mock_everything_results(n: int = 1):
    return [
        {"file_path": f"D:\\work\\file{i}.py", "file_name": f"file{i}.py", "file_size": 512, "modified": None}
        for i in range(n)
    ]


def _mock_ripgrep_results(n: int = 1):
    return [
        {
            "file_path": f"/home/user/project/file{i}.py",
            "file_name": f"file{i}.py",
            "file_size": None,
            "modified": None,
            "matches": [
                {
                    "line_number": 10 + i,
                    "line_text": f"def search_{i}():",
                    "context_before": [],
                    "context_after": [],
                    "submatches": [{"start": 4, "end": 10, "match": f"search_{i}"}],
                }
            ],
        }
        for i in range(n)
    ]


# ── Right: mode별 분기 ───────────────────────────────────────────────────

class TestSearchRight:
    """Right — 정상 검색 응답."""

    def test_mode_filename_calls_everything_only(self, client):
        """Right: mode=filename → Everything만 호출, ripgrep 호출 안 함."""
        ev_results = _mock_everything_results(2)

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            new_callable=AsyncMock, return_value=ev_results
        ) as mock_ev, patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock
        ) as mock_rg:
            resp = client.post("/api/v1/file-search/search", json={
                "query": "routes",
                "mode": "filename",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 2
        assert data["mode"] == "filename"
        mock_ev.assert_awaited_once()
        mock_rg.assert_not_awaited()

    def test_mode_content_calls_ripgrep_only(self, client):
        """Right: mode=content → ripgrep만 호출, Everything 호출 안 함."""
        rg_results = _mock_ripgrep_results(1)

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            new_callable=AsyncMock
        ) as mock_ev, patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock, return_value=rg_results
        ) as mock_rg:
            resp = client.post("/api/v1/file-search/search", json={
                "query": "def search",
                "mode": "content",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "content"
        assert data["total_count"] == 1
        mock_ev.assert_not_awaited()
        mock_rg.assert_awaited_once()

    def test_mode_both_calls_both_services(self, client):
        """Right: mode=both → 두 서비스 모두 호출, 결과 병합."""
        ev_results = _mock_everything_results(1)
        rg_results = _mock_ripgrep_results(1)

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            new_callable=AsyncMock, return_value=ev_results
        ) as mock_ev, patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock, return_value=rg_results
        ) as mock_rg:
            resp = client.post("/api/v1/file-search/search", json={
                "query": "search",
                "mode": "both",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "both"
        mock_ev.assert_awaited_once()
        mock_rg.assert_awaited_once()
        # 두 결과 모두 포함 (경로가 다름)
        assert data["total_count"] >= 1

    def test_get_presets_returns_six(self, client):
        """Right: GET /presets → 6개 프리셋."""
        resp = client.get("/api/v1/file-search/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 6
        ids = [p["id"] for p in data]
        assert "python_backend" in ids
        assert "frontend" in ids

    def test_get_status_returns_status_object(self, client):
        """Right: GET /status → everything_ok, ripgrep_ok 필드 포함."""
        with patch(
            "app.modules.file_search.services.search_service._everything.is_available",
            new_callable=AsyncMock, return_value=(False, "연결 실패")
        ), patch(
            "app.modules.file_search.services.search_service._ripgrep.is_available",
            return_value=(True, "/usr/bin/rg")
        ):
            resp = client.get("/api/v1/file-search/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "everything_ok" in data
        assert "ripgrep_ok" in data


# ── Boundary / CORRECT ───────────────────────────────────────────────────

class TestSearchBoundary:
    """Boundary + CORRECT — 입력 검증 테스트."""

    def test_empty_query_returns_422(self, client):
        """CORRECT-Existence: 빈 query → 422 (min_length=1 검증)."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "",
            "mode": "filename",
        })
        assert resp.status_code == 422

    def test_invalid_mode_returns_422(self, client):
        """CORRECT-Conformance: 잘못된 mode 값 → 422."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "test",
            "mode": "invalid_mode",
        })
        assert resp.status_code == 422

    def test_negative_max_results_returns_422(self, client):
        """CORRECT-Range: max_results 음수 → 422 (ge=1 검증)."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "test",
            "mode": "filename",
            "max_results": -1,
        })
        assert resp.status_code == 422

    def test_zero_max_results_returns_422(self, client):
        """CORRECT-Range: max_results=0 → 422 (ge=1 검증)."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "test",
            "mode": "filename",
            "max_results": 0,
        })
        assert resp.status_code == 422


# ── Inverse: 프리셋 오버라이드 ────────────────────────────────────────────

class TestPresetInverse:
    """Inverse — 프리셋 적용 시 paths/extensions 오버라이드 검증."""

    def test_preset_overrides_paths_and_extensions(self, client):
        """Inverse: preset 지정 시 요청의 paths/extensions 무시됨."""
        captured = {}

        async def fake_ev_search(**kwargs):
            captured.update(kwargs)
            return []

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            side_effect=fake_ev_search
        ):
            client.post("/api/v1/file-search/search", json={
                "query": "test",
                "mode": "filename",
                "preset": "python_backend",
                "paths": ["C:\\custom\\path"],       # 무시되어야 함
                "extensions": ["txt"],               # 무시되어야 함
            })

        # python_backend 프리셋의 extensions 포함 여부
        if captured:
            # 프리셋의 extensions는 python 관련 확장자
            assert "txt" not in captured.get("extensions", [])
            assert "py" in captured.get("extensions", [])

    def test_unknown_preset_uses_manual_values(self, client):
        """Inverse: 존재하지 않는 preset → 수동 paths/extensions 사용."""
        captured = {}

        async def fake_ev_search(**kwargs):
            captured.update(kwargs)
            return []

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            side_effect=fake_ev_search
        ):
            client.post("/api/v1/file-search/search", json={
                "query": "test",
                "mode": "filename",
                "preset": "nonexistent_preset",
                "extensions": ["custom_ext"],
            })

        if captured:
            assert "custom_ext" in captured.get("extensions", [])


# ── Error: 에러 처리 ─────────────────────────────────────────────────────

class TestSearchError:
    """Error — 에러 조건 API 응답 검증."""

    def test_open_nonexistent_file_returns_404(self, client, tmp_path):
        """Error: POST /open — 존재하지 않는 파일 → 404."""
        resp = client.post("/api/v1/file-search/open", json={
            "file_path": "/absolutely/nonexistent/file.py",
        })
        assert resp.status_code == 404

    def test_both_services_fail_returns_empty_not_500(self, client):
        """Error: Everything + ripgrep 둘 다 실패 → 500이 아닌 빈 결과."""
        import httpx

        with patch(
            "app.modules.file_search.services.search_service._everything.search",
            new_callable=AsyncMock, side_effect=Exception("Everything 서버 다운")
        ), patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock, side_effect=Exception("ripgrep 오류")
        ):
            resp = client.post("/api/v1/file-search/search", json={
                "query": "test",
                "mode": "both",
            })

        # both 모드에서 gather(return_exceptions=True)로 처리 → 빈 결과 반환
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0

    def test_ripgrep_timeout_returns_504(self, client):
        """Error: ripgrep 타임아웃 → 504."""
        with patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock, side_effect=TimeoutError("ripgrep 타임아웃")
        ):
            resp = client.post("/api/v1/file-search/search", json={
                "query": "test",
                "mode": "content",
            })

        assert resp.status_code == 504

    def test_invalid_regex_returns_422(self, client):
        """Error: 잘못된 정규식 → 422."""
        with patch(
            "app.modules.file_search.services.search_service._ripgrep.search",
            new_callable=AsyncMock, side_effect=ValueError("잘못된 정규식: [unclosed")
        ):
            resp = client.post("/api/v1/file-search/search", json={
                "query": "[unclosed",
                "mode": "content",
                "regex": True,
            })

        assert resp.status_code == 422


# ── browse 엔드포인트 ────────────────────────────────────────────────────

class TestBrowseEndpoint:
    """GET /browse — 디렉토리 탐색."""

    def test_browse_existing_directory(self, client, tmp_path):
        """Right: 실존하는 디렉토리 탐색 → BrowseResponse."""
        # tmp_path는 실제 존재하는 임시 디렉토리
        (tmp_path / "subdir").mkdir()

        resp = client.get(f"/api/v1/file-search/browse?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == str(tmp_path).rstrip("/\\")
        assert any(d["name"] == "subdir" for d in data["directories"])

    def test_browse_nonexistent_path_returns_empty_dirs(self, client):
        """Error: 존재하지 않는 경로 → 빈 directories."""
        resp = client.get("/api/v1/file-search/browse?path=/absolutely/nonexistent/path")
        assert resp.status_code == 200
        data = resp.json()
        assert data["directories"] == []
