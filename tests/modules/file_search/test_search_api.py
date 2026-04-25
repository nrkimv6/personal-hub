"""
파일 검색 API 통합 테스트

Right-BICEP / CORRECT 패턴:
- Right:       202 비동기 수락, 폴링 엔드포인트, presets, status
- Boundary:    빈 query → 422, 잘못된 mode → 422, max_results 음수 → 422
- Inverse:     preset 적용 시 paths/extensions 오버라이드
- Error:       없는 파일 open → 404, 없는 search_id → 404
- CORRECT-Conformance: 잘못된 mode enum → 422
- CORRECT-Range:       max_results 음수 → 422
- CORRECT-Existence:   null query → 422

변경 사항 (2026-02-23):
  POST /search: 동기 → 비동기 (202 + search_id)
  GET /search/{id}: 폴링 엔드포인트 신규 추가
"""
import json
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


# ── Right: POST /search 비동기 수락 ────────────────────────────────────────

class TestSearchRight:
    """Right — POST /search 202 수락 + 폴링 응답."""

    def test_mode_filename_returns_202(self, client):
        """Right: POST /search mode=filename → 202 Accepted + search_id."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "routes",
            "mode": "filename",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "search_id" in data
        assert data["status"] in ("pending", "queued")

    def test_mode_content_returns_202(self, client):
        """Right: POST /search mode=content → 202 Accepted + search_id."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "def search",
            "mode": "content",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "search_id" in data

    def test_mode_both_returns_202(self, client):
        """Right: POST /search mode=both → 202 Accepted + search_id."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "search",
            "mode": "both",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "search_id" in data

    def test_poll_nonexistent_returns_404(self, client):
        """Right: GET /search/{unknown_id} → 404."""
        resp = client.get("/api/v1/file-search/search/nonexistent-uuid")
        assert resp.status_code == 404

    def test_poll_pending_returns_status(self, client):
        """Right: POST /search 후 즉시 GET → status=pending/queued."""
        post_resp = client.post("/api/v1/file-search/search", json={
            "query": "routes",
            "mode": "filename",
        })
        assert post_resp.status_code == 202
        search_id = post_resp.json()["search_id"]

        poll_resp = client.get(f"/api/v1/file-search/search/{search_id}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["search_id"] == search_id
        assert data["status"] in ("pending", "queued", "processing", "completed", "failed")

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

    def test_preset_search_returns_202(self, client):
        """Inverse: preset 지정 시에도 202 반환."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "test",
            "mode": "filename",
            "preset": "python_backend",
            "paths": ["C:\\custom\\path"],
            "extensions": ["txt"],
        })
        assert resp.status_code == 202
        assert "search_id" in resp.json()

    def test_unknown_preset_returns_202(self, client):
        """Inverse: 존재하지 않는 preset도 202 반환 (워커에서 처리)."""
        resp = client.post("/api/v1/file-search/search", json={
            "query": "test",
            "mode": "filename",
            "preset": "nonexistent_preset",
            "extensions": ["custom_ext"],
        })
        assert resp.status_code == 202


# ── Error: 에러 처리 ─────────────────────────────────────────────────────

class TestSearchError:
    """Error — 에러 조건 API 응답 검증."""

    def test_open_nonexistent_file_returns_404(self, client, tmp_path):
        """Error: POST /open — 존재하지 않는 파일 → 404."""
        resp = client.post("/api/v1/file-search/open", json={
            "file_path": "/absolutely/nonexistent/file.py",
        })
        assert resp.status_code == 404

    def test_poll_nonexistent_search_id_returns_404(self, client):
        """Error: GET /search/{id} — 존재하지 않는 search_id → 404."""
        resp = client.get("/api/v1/file-search/search/totally-invalid-uuid-123")
        assert resp.status_code == 404

    def test_poll_completed_with_result(self, client):
        """Error/Right: 완료된 검색 결과 폴링 → result 필드 포함."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest
        from app.modules.file_search.schemas import SearchResponse

        # 직접 DB에 완료된 요청 삽입
        db = SessionLocal()
        try:
            mock_result = SearchResponse(
                results=[],
                total_count=0,
                search_time_ms=123,
                mode="filename",
                truncated=False,
            )
            req = FileSearchRequest(
                search_id="test-completed-uuid",
                status=FileSearchRequest.STATUS_COMPLETED,
                request_json='{"query":"test","mode":"filename","regex":false,"case_sensitive":false,'
                             '"paths":[],"extensions":[],"excludes":[],"max_results":100,"context_lines":2}',
                result_json=mock_result.model_dump_json(),
                search_time_ms=123,
            )
            db.add(req)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/v1/file-search/search/test-completed-uuid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] is not None
        assert data["result"]["total_count"] == 0

        # 정리
        db = SessionLocal()
        try:
            db.query(FileSearchRequest).filter_by(search_id="test-completed-uuid").delete()
            db.commit()
        finally:
            db.close()

    def test_poll_failed_with_error_message(self, client):
        """Error: 실패한 검색 결과 폴링 → error_message 필드."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        db = SessionLocal()
        try:
            req = FileSearchRequest(
                search_id="test-failed-uuid",
                status=FileSearchRequest.STATUS_FAILED,
                request_json='{"query":"test","mode":"content","regex":false,"case_sensitive":false,'
                             '"paths":[],"extensions":[],"excludes":[],"max_results":100,"context_lines":2}',
                error_message="ripgrep not found",
            )
            db.add(req)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/v1/file-search/search/test-failed-uuid")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "ripgrep not found"

        # 정리
        db = SessionLocal()
        try:
            db.query(FileSearchRequest).filter_by(search_id="test-failed-uuid").delete()
            db.commit()
        finally:
            db.close()


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


# ── history / suggestions 엔드포인트 ─────────────────────────────────────

class TestHistorySuggestions:
    def test_history_excludes_plan_quick(self, client):
        """Right: GET /history는 origin=file-search completed만 반환."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest
        from app.modules.file_search.schemas import FileMatch, SearchResponse

        db = SessionLocal()
        try:
            mock_result = SearchResponse(
                results=[FileMatch(file_path="D:\\work\\a.md", file_name="a.md")],
                total_count=1,
                search_time_ms=10,
                mode="content",
                truncated=False,
            )
            req_file_search = FileSearchRequest(
                search_id="hist-file-search",
                status=FileSearchRequest.STATUS_COMPLETED,
                created_at="2026-04-25 21:00:00",
                request_json=json.dumps({
                    "query": "Alpha",
                    "origin": "file-search",
                    "mode": "content",
                    "regex": False,
                    "case_sensitive": False,
                    "paths": [],
                    "extensions": [],
                    "excludes": [],
                    "preset": None,
                    "max_results": 100,
                    "context_lines": 2,
                }),
                result_json=mock_result.model_dump_json(),
                search_time_ms=10,
            )
            req_plan_quick = FileSearchRequest(
                search_id="hist-plan-quick",
                status=FileSearchRequest.STATUS_COMPLETED,
                created_at="2026-04-25 21:01:00",
                request_json=json.dumps({
                    "query": "Alpha",
                    "origin": "plan-quick",
                    "mode": "content",
                    "regex": False,
                    "case_sensitive": False,
                    "paths": [],
                    "extensions": [],
                    "excludes": [],
                    "preset": None,
                    "max_results": 100,
                    "context_lines": 2,
                }),
                result_json=mock_result.model_dump_json(),
                search_time_ms=10,
            )
            db.add(req_file_search)
            db.add(req_plan_quick)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/v1/file-search/history?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        ids = [x["search_id"] for x in data]
        assert "hist-file-search" in ids
        assert "hist-plan-quick" not in ids
        item = next(x for x in data if x["search_id"] == "hist-file-search")
        assert item["origin"] == "file-search"
        assert item["request"]["origin"] == "file-search"
        assert item["query"] == "Alpha"
        assert item["total_count"] == 1
        assert "a.md" in item["sample_files"]

        # 정리
        db = SessionLocal()
        try:
            db.query(FileSearchRequest).filter(
                FileSearchRequest.search_id.in_(["hist-file-search", "hist-plan-quick"])
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def test_suggestions_normalizes_and_excludes_plan_quick(self, client):
        """Right: GET /suggestions는 빈도 desc + 최근 사용 desc 정렬, plan-quick 제외."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        query_base = "hello___UNITTEST__2026-04-25"
        file_search_count = 40
        plan_quick_count = 10

        db = SessionLocal()
        try:
            rows = []
            for i in range(file_search_count):
                rows.append(
                    FileSearchRequest(
                        search_id=f"sug-fs-{i}",
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-25 10:{i:02d}:00",
                        request_json=json.dumps({
                            "query": query_base if i % 2 == 0 else query_base.upper(),
                            "origin": "file-search",
                            "mode": "both",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [],
                            "extensions": [],
                            "excludes": [],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }),
                        result_json="{}",
                        search_time_ms=1,
                    )
                )

            for i in range(plan_quick_count):
                rows.append(
                    FileSearchRequest(
                        search_id=f"sug-pq-{i}",
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-25 10:{50 + i:02d}:00",
                        request_json=json.dumps({
                            "query": query_base,
                            "origin": "plan-quick",
                            "mode": "both",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [],
                            "extensions": [],
                            "excludes": [],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }),
                        result_json="{}",
                        search_time_ms=1,
                    )
                )

            for r in rows:
                db.add(r)
            db.commit()
        finally:
            db.close()

        resp = client.get("/api/v1/file-search/suggestions?limit=50")
        assert resp.status_code == 200
        data = resp.json()
        item = next((x for x in data if x["query"].lower() == query_base.lower()), None)
        assert item is not None
        assert item["count"] == file_search_count
        assert item["last_used_at"] == "2026-04-25 10:39:00"

        # 정리
        db = SessionLocal()
        try:
            db.query(FileSearchRequest).filter(
                FileSearchRequest.search_id.like("sug-fs-%") | FileSearchRequest.search_id.like("sug-pq-%")
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
