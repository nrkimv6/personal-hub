"""
T3 통합 TC: plan scope(registered_paths) + file-search(plan-quick origin) 스냅샷 저장/추천 제외 검증.

- dev-runner /plans/paths 가 등록된 plan 경로만 반환하는지
- 그 경로를 scope(paths)로 사용해 file-search 요청을 저장했을 때 request_json이 보존되는지
- origin=plan-quick 요청이 file-search history/suggestions 집계에 섞이지 않는지
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.plans import router as dev_runner_plans_router
from app.modules.dev_runner.services.plan_service import plan_service
from app.modules.file_search.routes import router as file_search_router


@pytest.fixture
def integrated_client(tmp_path):
    """file-search + dev-runner(plans only) 라우터를 함께 올린 TestClient.

    dev-runner plan_service는 전역 싱글톤이므로, config 격리 + 상태 스냅샷/복원까지 수행한다.
    """
    reg_file = tmp_path / "registered_paths.json"
    ign_file = tmp_path / "ignored_plans.json"
    reg_file.write_text("[]", encoding="utf-8")
    ign_file.write_text("[]", encoding="utf-8")

    mock_config = MagicMock()
    mock_config.REGISTERED_PATHS_FILE = reg_file
    mock_config.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
    mock_config.IGNORED_PLANS_FILE = ign_file
    mock_config.WTOOLS_BASE_DIR = tmp_path / "wtools"
    mock_config.PLAN_DIR = Path("common/docs/plan")
    mock_config.PROJECT_DIRS = []
    mock_config.ALLOWED_PATHS = [str(tmp_path.resolve())]
    mock_config.LOG_DIR = Path("common/logs")
    mock_config.LOG_FILE_PATTERN = "plan-runner-*.log"

    # plan_service singleton state snapshot (avoid leaking across suites)
    orig_registered = list(getattr(plan_service, "_registered_paths", []))
    orig_ignored = list(getattr(plan_service, "_ignored_plans", []))
    orig_archive_cache = dict(getattr(plan_service, "_archive_cache", {}))
    orig_plans_cache = getattr(plan_service, "_plans_cache", None)
    orig_plans_cache_with_ignored = getattr(plan_service, "_plans_cache_with_ignored", None)
    orig_plans_cache_time = getattr(plan_service, "_plans_cache_time", 0)

    with patch("app.modules.dev_runner.services.plan_service.config", mock_config), \
            patch("app.modules.dev_runner.services.plan_path_registry.config", mock_config), \
            patch("app.modules.dev_runner.services.plan_path_helpers.config", mock_config), \
            patch("app.modules.dev_runner.services.plan_scanner.config", mock_config, create=True):
        # Reset to isolated config
        plan_service._registered_paths = []
        plan_service._ignored_plans = []
        plan_service._archive_cache = {}
        plan_service._plans_cache = None
        plan_service._plans_cache_with_ignored = None
        plan_service._plans_cache_time = 0
        plan_service._load_registered_paths()
        plan_service._load_ignored_plans()

        app = FastAPI()
        app.include_router(file_search_router)
        app.include_router(dev_runner_plans_router, prefix="/api/v1/dev-runner")

        yield TestClient(app), reg_file

    # Restore singleton state
    plan_service._registered_paths = orig_registered
    plan_service._ignored_plans = orig_ignored
    plan_service._archive_cache = orig_archive_cache
    plan_service._plans_cache = orig_plans_cache
    plan_service._plans_cache_with_ignored = orig_plans_cache_with_ignored
    plan_service._plans_cache_time = orig_plans_cache_time


def test_plan_quick_scope_registered_paths_snapshot_and_exclusion(integrated_client, tmp_path):
    """등록된 plan scope를 사용한 plan-quick 검색은 스냅샷이 저장되지만 추천/이력에 섞이면 안 된다."""
    client, reg_file = integrated_client

    # 1) plan scope 준비 (registered_paths.json + 실제 md 파일)
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plan_dir / "2026-04-25_plan_quick_integration.md"

    query = "PLAN_QUICK_SCOPE___UNITTEST__2026-04-25"
    plan_file.write_text(f"# integration\n\n{query}\n", encoding="utf-8")

    reg_file.write_text(
        json.dumps([{"path": str(plan_dir.resolve()), "type": "plan"}], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    plan_service._load_registered_paths()

    # 2) dev-runner listPaths 결과가 scope로 사용 가능해야 함
    resp = client.get("/api/v1/dev-runner/plans/paths")
    assert resp.status_code == 200
    paths = resp.json()
    matching = [p for p in paths if p["path"] == str(plan_dir.resolve()) and p["path_type"] == "plan"]
    assert len(matching) == 1
    assert matching[0]["plan_count"] == 1

    # 3) file-search 요청 생성 (origin=plan-quick, scope=registered plan paths)
    post = client.post(
        "/api/v1/file-search/search",
        json={
            "query": query,
            "mode": "content",
            "origin": "plan-quick",
            "paths": [str(plan_dir.resolve())],
        },
    )
    assert post.status_code == 202
    search_id = post.json()["search_id"]

    # 4) 저장된 request_json 스냅샷 보존 + completed row 생성 (워커 수행을 DB에서 모의)
    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.schemas import FileMatch, SearchResponse

    db = SessionLocal()
    try:
        row = db.query(FileSearchRequest).filter_by(search_id=search_id).first()
        assert row is not None

        request_json = json.loads(row.request_json)
        assert request_json["origin"] == "plan-quick"
        assert request_json["paths"] == [str(plan_dir.resolve())]

        result = SearchResponse(
            results=[
                FileMatch(
                    file_path=str(plan_file),
                    file_name=plan_file.name,
                    match_source="content",
                )
            ],
            total_count=1,
            search_time_ms=1,
            mode="content",
            truncated=False,
        )
        row.status = FileSearchRequest.STATUS_COMPLETED
        row.result_json = result.model_dump_json()
        row.search_time_ms = 1
        db.commit()
    finally:
        db.close()

    # 5) origin=plan-quick은 file-search suggestions/history/frequent-combos 집계에서 제외되어야 함
    sug = client.get("/api/v1/file-search/suggestions?limit=50")
    assert sug.status_code == 200
    assert all(query.lower() != s["query"].lower() for s in sug.json())

    hist = client.get("/api/v1/file-search/history?limit=50")
    assert hist.status_code == 200
    ids = [h["search_id"] for h in hist.json()]
    assert search_id not in ids

    combos = client.get("/api/v1/file-search/frequent-combos?limit=50")
    assert combos.status_code == 200
    assert all(query.lower() != item["label"].lower() for item in combos.json())

    # cleanup
    db = SessionLocal()
    try:
        db.query(FileSearchRequest).filter_by(search_id=search_id).delete()
        db.commit()
    finally:
        db.close()


def test_history_suggestions_and_combos_scan_past_recent_plan_quick_noise(integrated_client, tmp_path):
    """최근 registered plan noise가 많아도 file-search 집계는 뒤쪽 target row를 복구해야 한다."""
    client, reg_file = integrated_client

    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    target_file = plan_dir / "2026-04-27_target.md"
    target_file.write_text("# target\n\nRecovered Query\n", encoding="utf-8")

    reg_file.write_text(
        json.dumps([{"path": str(plan_dir.resolve()), "type": "plan"}], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    plan_service._load_registered_paths()

    from app.database import SessionLocal
    from app.models.file_search_request import FileSearchRequest
    from app.modules.file_search.schemas import FileMatch, SearchResponse

    db = SessionLocal()
    ids: list[str] = []
    try:
        for i in range(2050):
            search_id = f"int-noise-{i}"
            ids.append(search_id)
            db.add(
                FileSearchRequest(
                    search_id=search_id,
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=f"2026-04-27 23:{59 - (i % 60):02d}:{59 - (i // 60):02d}",
                    request_json=json.dumps(
                        {
                            "query": f"noise-{i}",
                            "origin": "plan-quick",
                            "mode": "content",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [str(plan_dir.resolve())],
                            "extensions": ["md"],
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

        db.add(
            FileSearchRequest(
                search_id="int-malformed",
                status=FileSearchRequest.STATUS_COMPLETED,
                created_at="2026-04-27 12:30:00",
                request_json="{bad-json}",
                result_json="{}",
                search_time_ms=1,
            )
        )
        ids.append("int-malformed")

        target_payloads = [
            ("int-target-history", "file-search", "Recovered Query", "9999-12-31 23:59:50"),
            ("int-target-combo", "legacy-tool", "Recovered Query", "9999-12-31 23:59:51"),
        ]
        for search_id, origin, query, created_at in target_payloads:
            ids.append(search_id)
            db.add(
                FileSearchRequest(
                    search_id=search_id,
                    status=FileSearchRequest.STATUS_COMPLETED,
                    created_at=created_at,
                    request_json=json.dumps(
                        {
                            "query": query,
                            "origin": origin,
                            "mode": "content",
                            "regex": False,
                            "case_sensitive": False,
                            "paths": [str(plan_dir.resolve())],
                            "extensions": ["md"],
                            "excludes": [],
                            "preset": None,
                            "max_results": 100,
                            "context_lines": 2,
                        }
                    ),
                    result_json=SearchResponse(
                        results=[FileMatch(file_path=str(target_file), file_name=target_file.name, match_source="content")],
                        total_count=1,
                        search_time_ms=1,
                        mode="content",
                        truncated=False,
                    ).model_dump_json(),
                    search_time_ms=1,
                )
            )
        db.commit()

        hist = client.get("/api/v1/file-search/history?limit=10")
        assert hist.status_code == 200
        hist_ids = [item["search_id"] for item in hist.json()]
        assert "int-target-combo" in hist_ids
        assert all(not item_id.startswith("int-noise-") for item_id in hist_ids)

        sug = client.get("/api/v1/file-search/suggestions?limit=10")
        assert sug.status_code == 200
        sug_item = next((item for item in sug.json() if item["query"] == "Recovered Query"), None)
        assert sug_item is not None
        assert sug_item["count"] == 2

        combos = client.get("/api/v1/file-search/frequent-combos?limit=10")
        assert combos.status_code == 200
        combo_item = next((item for item in combos.json() if item["label"] == "Recovered Query"), None)
        assert combo_item is not None
        assert combo_item["count"] == 2
        assert combo_item["request"]["origin"] == "file-search"
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
