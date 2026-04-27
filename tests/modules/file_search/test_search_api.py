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
        import uuid
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest
        from app.modules.file_search.schemas import FileMatch, SearchResponse

        seed = uuid.uuid4().hex[:8]
        file_search_id = f"hist-fs-{seed}"
        plan_quick_id = f"hist-pq-{seed}"

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
                search_id=file_search_id,
                status=FileSearchRequest.STATUS_COMPLETED,
                # Ensure this row stays within scan_limit even if the test DB already has many completed rows.
                created_at="9999-12-31 23:59:58",
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
                search_id=plan_quick_id,
                status=FileSearchRequest.STATUS_COMPLETED,
                created_at="9999-12-31 23:59:59",
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

            resp = client.get("/api/v1/file-search/history?limit=10")
            assert resp.status_code == 200
            data = resp.json()
            ids = [x["search_id"] for x in data]
            assert file_search_id in ids
            assert plan_quick_id not in ids
            item = next(x for x in data if x["search_id"] == file_search_id)
            assert item["origin"] == "file-search"
            assert item["request"]["origin"] == "file-search"
            assert item["query"] == "Alpha"
            assert item["total_count"] == 1
            assert "a.md" in item["sample_files"]
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_([file_search_id, plan_quick_id])
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_suggestions_normalizes_and_excludes_plan_quick(self, client):
        """Right: GET /suggestions는 빈도 desc + 최근 사용 desc 정렬, plan-quick 제외."""
        import uuid
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        seed = uuid.uuid4().hex[:8]
        query_base = f"hello___UNITTEST__2026-04-25__{seed}"
        file_search_count = 40
        plan_quick_count = 10

        ids: list[str] = []
        db = SessionLocal()
        try:
            rows = []
            for i in range(file_search_count):
                rows.append(
                    FileSearchRequest(
                        search_id=f"sugfs-{seed}-{i}",
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
                ids.append(rows[-1].search_id)

            for i in range(plan_quick_count):
                rows.append(
                    FileSearchRequest(
                        search_id=f"sugpq-{seed}-{i}",
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
                ids.append(rows[-1].search_id)

            for r in rows:
                db.add(r)
            db.commit()

            resp = client.get("/api/v1/file-search/suggestions?limit=50")
            assert resp.status_code == 200
            data = resp.json()
            item = next((x for x in data if x["query"].lower() == query_base.lower()), None)
            assert item is not None
            assert item["count"] == file_search_count
            assert item["last_used_at"] == "2026-04-25 10:39:00"
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_frequent_combos_returns_count_desc_then_last_used_desc(self, client):
        """Right: GET /frequent-combos는 count desc + 최근 사용 desc 정렬로 반환."""
        import uuid
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        seed = uuid.uuid4().hex[:8]
        ids = [
            f"combo-alpha-{seed}-1",
            f"combo-alpha-{seed}-2",
            f"combo-beta-{seed}",
        ]
        db = SessionLocal()
        try:
            rows = [
                FileSearchRequest(
                    search_id=ids[0],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="9999-12-31 23:59:50",
                    request_json=json.dumps({
                        "query": "Alpha Combo",
                        "origin": "file-search",
                        "mode": "content",
                        "regex": False,
                        "case_sensitive": False,
                        "paths": [r"D:\work\project\tools\monitor-page\frontend"],
                        "extensions": ["svelte"],
                        "excludes": ["node_modules"],
                        "preset": "frontend",
                        "max_results": 100,
                        "context_lines": 2,
                    }),
                    result_json="{}",
                    search_time_ms=1,
                ),
                FileSearchRequest(
                    search_id=ids[1],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="9999-12-31 23:59:52",
                    request_json=json.dumps({
                        "query": "alpha combo",
                        "origin": "file-search",
                        "mode": "content",
                        "regex": False,
                        "case_sensitive": False,
                        "paths": [r"D:\work\project\tools\monitor-page\frontend"],
                        "extensions": ["svelte"],
                        "excludes": ["node_modules"],
                        "preset": "frontend",
                        "max_results": 100,
                        "context_lines": 2,
                    }),
                    result_json="{}",
                    search_time_ms=1,
                ),
                FileSearchRequest(
                    search_id=ids[2],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="9999-12-31 23:59:51",
                    request_json=json.dumps({
                        "query": "Beta Combo",
                        "origin": "file-search",
                        "mode": "filename",
                        "regex": False,
                        "case_sensitive": False,
                        "paths": [r"D:\work\project\tools\monitor-page\app"],
                        "extensions": ["py"],
                        "excludes": [],
                        "preset": None,
                        "max_results": 100,
                        "context_lines": 2,
                    }),
                    result_json="{}",
                    search_time_ms=1,
                ),
            ]
            for row in rows:
                db.add(row)
            db.commit()

            resp = client.get("/api/v1/file-search/frequent-combos?limit=50")
            assert resp.status_code == 200
            data = resp.json()
            target = [item for item in data if item["label"].lower() in {"alpha combo", "beta combo"}]
            assert len(target) == 2
            assert target[0]["label"] == "alpha combo"
            assert target[0]["count"] == 2
            assert target[0]["last_used_at"] == "9999-12-31 23:59:52"
            assert target[1]["label"] == "Beta Combo"
            assert target[1]["count"] == 1
            assert target[0]["request"]["preset"] == "frontend"
            assert "summary_tokens" in target[0]
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_frequent_combos_skips_malformed_request_json(self, client):
        """Error: malformed request_json row는 /frequent-combos 집계에서 건너뛴다."""
        import uuid
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        seed = uuid.uuid4().hex[:8]
        ids = [f"combo-bad-{seed}", f"combo-good-{seed}"]
        db = SessionLocal()
        try:
            db.add(
                FileSearchRequest(
                    search_id=ids[0],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="9999-12-31 23:59:58",
                    request_json="{bad-json}",
                    result_json="{}",
                    search_time_ms=1,
                )
            )
            db.add(
                FileSearchRequest(
                    search_id=ids[1],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="9999-12-31 23:59:59",
                    request_json=json.dumps({
                        "query": "Good Combo",
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
            db.commit()

            resp = client.get("/api/v1/file-search/frequent-combos?limit=50")
            assert resp.status_code == 200
            data = resp.json()
            good_combo = next((item for item in data if item["label"] == "Good Combo"), None)
            assert good_combo is not None
            assert good_combo["last_used_at"] == "9999-12-31 23:59:59"
            assert all(item["label"] != "{bad-json}" for item in data)
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_frequent_combos_splits_different_paths_extensions_and_excludes(self, client):
        """Right: paths/extensions/excludes 조합이 다르면 별도 item으로 분리된다."""
        import uuid
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        seed = uuid.uuid4().hex[:8]
        ids = [f"combo-split-{seed}-1", f"combo-split-{seed}-2"]
        db = SessionLocal()
        try:
            variants = [
                {
                    "paths": [r"D:\work\project\tools\monitor-page\app"],
                    "extensions": ["py"],
                    "excludes": ["__pycache__"],
                },
                {
                    "paths": [r"D:\work\project\tools\monitor-page\frontend"],
                    "extensions": ["svelte"],
                    "excludes": ["node_modules"],
                },
            ]
            for idx, variant in enumerate(variants):
                db.add(
                    FileSearchRequest(
                        search_id=ids[idx],
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"9999-12-31 23:59:5{idx}",
                        request_json=json.dumps({
                            "query": "Split Combo",
                            "origin": "file-search",
                            "mode": "content",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": variant["paths"],
                            "extensions": variant["extensions"],
                            "excludes": variant["excludes"],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }),
                        result_json="{}",
                        search_time_ms=1,
                    )
                )
            db.commit()

            resp = client.get("/api/v1/file-search/frequent-combos?limit=10")
            assert resp.status_code == 200
            data = [item for item in resp.json() if item["label"] == "Split Combo"]
            assert len(data) == 2
            assert any(item["request"]["paths"] == [r"D:\work\project\tools\monitor-page\app"] for item in data)
            assert any(item["request"]["paths"] == [r"D:\work\project\tools\monitor-page\frontend"] for item in data)
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_history_bias_scan_recovers_older_file_search_rows(self, client):
        """Right: 최근 plan-quick noise가 많아도 /history는 뒤쪽 file-search row를 찾아야 한다."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        db = SessionLocal()
        ids: list[str] = []
        try:
            for i in range(300):
                search_id = f"api-hist-noise-{i}"
                ids.append(search_id)
                db.add(
                    FileSearchRequest(
                        search_id=search_id,
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-27 23:{59 - (i % 60):02d}:{59 - (i // 60):02d}",
                        request_json=json.dumps({
                            "query": f"noise-{i}",
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
                        result_json="{}",
                        search_time_ms=1,
                    )
                )

            ids.append("api-hist-target")
            db.add(
                FileSearchRequest(
                    search_id="api-hist-target",
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="2026-04-27 20:00:00",
                    request_json=json.dumps({
                        "query": "Recovered History API",
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
                    result_json="{}",
                    search_time_ms=1,
                )
            )
            db.commit()

            resp = client.get("/api/v1/file-search/history?limit=1")
            assert resp.status_code == 200
            data = resp.json()
            assert [item["search_id"] for item in data] == ["api-hist-target"]
            assert data[0]["query"] == "Recovered History API"
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_suggestions_bias_scan_counts_older_file_search_rows(self, client):
        """Right: /suggestions는 recent noise 뒤의 file-search query count를 과소 집계하면 안 된다."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        db = SessionLocal()
        ids: list[str] = []
        try:
            for i in range(2100):
                search_id = f"api-sug-noise-{i}"
                ids.append(search_id)
                db.add(
                    FileSearchRequest(
                        search_id=search_id,
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-27 23:{59 - (i % 60):02d}:{59 - (i // 60):02d}",
                        request_json=json.dumps({
                            "query": f"noise-{i}",
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

            for i, query in enumerate(["Recovered Suggestion API", "recovered suggestion api", "RECOVERED SUGGESTION API"]):
                search_id = f"api-sug-target-{i}"
                ids.append(search_id)
                db.add(
                    FileSearchRequest(
                        search_id=search_id,
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-27 10:0{i}:00",
                        request_json=json.dumps({
                            "query": query,
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
            db.commit()

            resp = client.get("/api/v1/file-search/suggestions?limit=10")
            assert resp.status_code == 200
            item = next((row for row in resp.json() if row["query"].lower() == "recovered suggestion api"), None)
            assert item is not None
            assert item["count"] == 3
            assert item["last_used_at"] == "2026-04-27 10:02:00"
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()

    def test_frequent_combos_bias_scan_and_unknown_origin_fallback(self, client):
        """Right: /frequent-combos는 recent noise와 legacy origin row를 함께 처리해야 한다."""
        from app.database import SessionLocal
        from app.models.file_search_request import FileSearchRequest

        db = SessionLocal()
        ids: list[str] = []
        try:
            for i in range(2050):
                search_id = f"api-combo-noise-{i}"
                ids.append(search_id)
                db.add(
                    FileSearchRequest(
                        search_id=search_id,
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=f"2026-04-27 23:{59 - (i % 60):02d}:{59 - (i // 60):02d}",
                        request_json=json.dumps({
                            "query": f"noise-{i}",
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
                        result_json="{}",
                        search_time_ms=1,
                    )
                )

            ids.append("api-combo-malformed")
            db.add(
                FileSearchRequest(
                    search_id="api-combo-malformed",
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at="2026-04-27 09:30:00",
                    request_json="{bad-json}",
                    result_json="{}",
                    search_time_ms=1,
                )
            )

            for i, created_at in enumerate(["2026-04-27 09:00:00", "2026-04-27 09:01:00"]):
                search_id = f"api-combo-target-{i}"
                ids.append(search_id)
                db.add(
                    FileSearchRequest(
                        search_id=search_id,
                        status=FileSearchRequest.STATUS_COMPLETED,
                        created_at=created_at,
                        request_json=json.dumps({
                            "query": "Recovered Combo API",
                            "origin": "legacy-tool",
                            "mode": "content",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [r"D:\work\project\tools\monitor-page\app"],
                            "extensions": ["py"],
                            "excludes": [],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }),
                        result_json="{}",
                        search_time_ms=1,
                    )
                )
            db.commit()

            resp = client.get("/api/v1/file-search/frequent-combos?limit=10")
            assert resp.status_code == 200
            item = next((row for row in resp.json() if row["label"] == "Recovered Combo API"), None)
            assert item is not None
            assert item["count"] == 2
            assert item["request"]["origin"] == "file-search"
            assert item["last_used_at"] == "2026-04-27 09:01:00"
        finally:
            db.close()
            cleanup_db = SessionLocal()
            try:
                cleanup_db.query(FileSearchRequest).filter(
                    FileSearchRequest.search_id.in_(ids)
                ).delete(synchronize_session=False)
                cleanup_db.commit()
            finally:
                cleanup_db.close()
