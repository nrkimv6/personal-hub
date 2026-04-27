"""
파일 검색 SearchService 단위 테스트

- request_json/result_json 집계 내성 (malformed JSON skip)
- suggestions 정규화 + origin 분리
"""

import json


def _cleanup_requests(db, search_ids: list[str]):
    from app.models.file_search_request import FileSearchRequest

    if not search_ids:
        return
    db.query(FileSearchRequest).filter(FileSearchRequest.search_id.in_(search_ids)).delete(
        synchronize_session=False
    )
    db.commit()


def test_get_history_skips_malformed_json():
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.schemas import FileMatch, SearchResponse
    from app.modules.file_search.services.search_service import SearchService

    db = SessionLocal()
    ids = ["svc-hist-bad", "svc-hist-ok"]
    try:
        mock_result = SearchResponse(
            results=[FileMatch(file_path="D:\\work\\a.md", file_name="a.md")],
            total_count=1,
            search_time_ms=10,
            mode="content",
            truncated=False,
        )
        db.add(
            FileSearchRequest(
                search_id="svc-hist-bad",
                status=FileSearchRequest.STATUS_COMPLETED,
                # Ensure this row stays within scan_limit even if the test DB already has many completed rows.
                created_at="9999-12-31 23:59:58",
                request_json="{not-json}",
                result_json=mock_result.model_dump_json(),
                search_time_ms=10,
            )
        )
        db.add(
            FileSearchRequest(
                search_id="svc-hist-ok",
                status=FileSearchRequest.STATUS_COMPLETED,
                created_at="9999-12-31 23:59:59",
                request_json=json.dumps(
                    {
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
                    }
                ),
                result_json=mock_result.model_dump_json(),
                search_time_ms=10,
            )
        )
        db.commit()

        svc = SearchService()
        items = svc.get_history(db=db, limit=10, origin="file-search")
        ids_seen = [i.search_id for i in items]
        assert "svc-hist-ok" in ids_seen
        assert "svc-hist-bad" not in ids_seen
        ok = next(i for i in items if i.search_id == "svc-hist-ok")
        assert ok.query == "Alpha"
        assert ok.origin == "file-search"
        assert "a.md" in ok.sample_files
    finally:
        _cleanup_requests(db, ids)
        db.close()


def test_get_suggestions_normalizes_and_excludes_plan_quick():
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.services.search_service import SearchService

    query_base = "hello___UNITTEST__2026-04-25__search_service"

    db = SessionLocal()
    ids: list[str] = []
    try:
        # file-search 3회 (대소문자/공백 섞기), plan-quick 10회 (제외되어야 함)
        for i, q in enumerate([query_base, f"  {query_base}  ", query_base.upper()]):
            ids.append(f"svc-sug-fs-{i}")
            db.add(
                FileSearchRequest(
                    search_id=ids[-1],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=f"2026-04-25 13:0{i}:00",
                    request_json=json.dumps(
                        {
                            "query": q,
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
                        }
                    ),
                    result_json="{}",
                    search_time_ms=1,
                )
            )

        for i in range(10):
            ids.append(f"svc-sug-pq-{i}")
            db.add(
                FileSearchRequest(
                    search_id=ids[-1],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=f"2026-04-25 13:{50 + i:02d}:00",
                    request_json=json.dumps(
                        {
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
                        }
                    ),
                    result_json="{}",
                    search_time_ms=1,
                )
            )

        db.commit()

        svc = SearchService()
        suggestions = svc.get_suggestions(db=db, limit=50, origin="file-search")
        item = next((s for s in suggestions if s.query.lower() == query_base.lower()), None)
        assert item is not None
        assert item.count == 3
        assert item.last_used_at == "2026-04-25 13:02:00"
    finally:
        _cleanup_requests(db, ids)
        db.close()


def test_get_frequent_combos_groups_same_query_and_filters():
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.services.search_service import SearchService

    db = SessionLocal()
    ids: list[str] = []
    try:
        rows = [
            {
                "search_id": "svc-combo-group-1",
                "created_at": "2026-04-27 09:00:00",
                "request_json": {
                    "query": "Alpha Search",
                    "origin": "file-search",
                    "mode": "content",
                    "regex": False,
                    "case_sensitive": False,
                    "paths": [r"D:\work\project\tools\monitor-page\frontend"],
                    "extensions": ["ts", "svelte"],
                    "excludes": ["node_modules"],
                    "preset": "frontend",
                    "max_results": 100,
                    "context_lines": 2,
                },
            },
            {
                "search_id": "svc-combo-group-2",
                "created_at": "2026-04-27 09:01:00",
                "request_json": {
                    "query": " alpha   search ",
                    "origin": "file-search",
                    "mode": "content",
                    "regex": False,
                    "case_sensitive": False,
                    "paths": [r"D:\WORK\PROJECT\TOOLS\MONITOR-PAGE\FRONTEND"],
                    "extensions": ["svelte", "ts"],
                    "excludes": ["node_modules"],
                    "preset": "frontend",
                    "max_results": 100,
                    "context_lines": 2,
                },
            },
            {
                "search_id": "svc-combo-group-3",
                "created_at": "2026-04-27 09:02:00",
                "request_json": {
                    "query": "ALPHA SEARCH",
                    "origin": "file-search",
                    "mode": "content",
                    "regex": False,
                    "case_sensitive": False,
                    "paths": [r"D:\work\project\tools\monitor-page\frontend"],
                    "extensions": ["ts", "svelte"],
                    "excludes": ["node_modules"],
                    "preset": "frontend",
                    "max_results": 100,
                    "context_lines": 2,
                },
            },
        ]
        ids.extend(row["search_id"] for row in rows)
        for row in rows:
            db.add(
                FileSearchRequest(
                    search_id=row["search_id"],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=row["created_at"],
                    request_json=json.dumps(row["request_json"]),
                    result_json="{}",
                    search_time_ms=1,
                )
            )
        db.commit()

        svc = SearchService()
        combos = svc.get_frequent_combos(db=db, limit=10, origin="file-search")
        combo = next((item for item in combos if item.label == "ALPHA SEARCH"), None)
        assert combo is not None
        assert combo.count == 3
        assert combo.last_used_at == "2026-04-27 09:02:00"
        assert combo.request.preset == "frontend"
        assert combo.request.paths == [r"D:\work\project\tools\monitor-page\frontend"]
        assert "내용" in combo.summary_tokens
    finally:
        _cleanup_requests(db, ids)
        db.close()


def test_get_frequent_combos_splits_different_filter_sets():
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.services.search_service import SearchService

    db = SessionLocal()
    ids = ["svc-combo-split-1", "svc-combo-split-2"]
    try:
        requests = [
            {
                "query": "Beta Search",
                "origin": "file-search",
                "mode": "content",
                "regex": False,
                "case_sensitive": False,
                "paths": [r"D:\work\project\tools\monitor-page\app"],
                "extensions": ["py"],
                "excludes": ["__pycache__"],
                "preset": None,
                "max_results": 100,
                "context_lines": 2,
            },
            {
                "query": "Beta Search",
                "origin": "file-search",
                "mode": "content",
                "regex": False,
                "case_sensitive": False,
                "paths": [r"D:\work\project\tools\monitor-page\app"],
                "extensions": ["ts"],
                "excludes": ["node_modules"],
                "preset": None,
                "max_results": 100,
                "context_lines": 2,
            },
        ]
        for idx, request_json in enumerate(requests):
            db.add(
                FileSearchRequest(
                    search_id=ids[idx],
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=f"2026-04-27 10:0{idx}:00",
                    request_json=json.dumps(request_json),
                    result_json="{}",
                    search_time_ms=1,
                )
            )
        db.commit()

        svc = SearchService()
        combos = [item for item in svc.get_frequent_combos(db=db, limit=10, origin="file-search") if item.label == "Beta Search"]
        assert len(combos) == 2
        token_sets = [set(item.summary_tokens) for item in combos]
        assert any(".py" in tokens for tokens in token_sets)
        assert any(".ts" in tokens for tokens in token_sets)
    finally:
        _cleanup_requests(db, ids)
        db.close()


def test_get_frequent_combos_excludes_plan_quick():
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.services.search_service import SearchService

    db = SessionLocal()
    ids = ["svc-combo-fs", "svc-combo-pq"]
    try:
        payloads = [
            ("svc-combo-fs", "file-search", "2026-04-27 11:00:00"),
            ("svc-combo-pq", "plan-quick", "2026-04-27 11:01:00"),
        ]
        for search_id, origin, created_at in payloads:
            db.add(
                FileSearchRequest(
                    search_id=search_id,
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=created_at,
                    request_json=json.dumps(
                        {
                            "query": "Gamma Search",
                            "origin": origin,
                            "mode": "both",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [],
                            "extensions": [],
                            "excludes": [],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }
                    ),
                    result_json="{}",
                    search_time_ms=1,
                )
            )
        db.commit()

        svc = SearchService()
        combos = svc.get_frequent_combos(db=db, limit=10, origin="file-search")
        combo = next((item for item in combos if item.label == "Gamma Search"), None)
        assert combo is not None
        assert combo.count == 1
        assert combo.last_used_at == "2026-04-27 11:00:00"
    finally:
        _cleanup_requests(db, ids)
        db.close()
