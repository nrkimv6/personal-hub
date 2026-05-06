"""T4 E2E: ArchiveTab 잔류 surface 검증.

ArchiveTab에 redirect banner/placeholder, 잔류 컴포넌트(Retrieval/Detail/Sync)가
존재하고, 운영 surface(candidate/execution queue)가 제거됐는지 smoke로 검증한다.
"""
import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e

ADMIN_URL = "http://localhost:6101"


def _json_response(route, payload):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))


def _install_archive_tab_routes(page: Page) -> None:
    def handle(route):
        url = route.request.url
        if "/api/v1/auth/me" in url:
            _json_response(route, {"username": "pytest", "is_admin": True})
            return
        if "/api/v1/system/mode" in url:
            _json_response(route, {"mode": "admin"})
            return
        if "/api/v1/system/liveness" in url:
            _json_response(route, {"status": "ok"})
            return
        if "/api/v1/dev-runner/plans/paths" in url:
            _json_response(route, [])
            return
        if "/api/v1/plans/records" in url and "retrieval" not in url:
            _json_response(route, [])
            return
        if "/api/v1/plans/retrieval/search" in url:
            _json_response(route, {"total": 0, "results": []})
            return
        if "/api/v1/plans/retrieval/metrics" in url:
            _json_response(route, {"total_plans": 0})
            return
        if "/api/v1/llm/requests" in url:
            _json_response(route, {"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1})
            return
        route.continue_()

    page.route("**/*", handle)


def test_archivetab_source_contract_no_forbidden_imports():
    """ArchiveTab.svelte에 금지된 운영 surface 참조가 없고 잔류 컴포넌트 import가 존재한다."""
    svelte_path = Path(
        r"D:\work\project\tools\monitor-page\frontend\src\routes\plans\ArchiveTab.svelte"
    )
    assert svelte_path.exists(), f"ArchiveTab.svelte not found at {svelte_path}"
    source = svelte_path.read_text(encoding="utf-8")

    # 금지 확인
    assert "PlanArchiveRequestDetailModal" not in source, "ArchiveTab must not import PlanArchiveRequestDetailModal"
    assert "archive-candidates" not in source, "ArchiveTab must not reference archive-candidates"
    assert "archive-executions" not in source, "ArchiveTab must not reference archive-executions"

    # 잔류 컴포넌트 존재 확인
    assert "ArchiveRetrievalPanel" in source, "ArchiveTab must import ArchiveRetrievalPanel"
    assert "ArchiveRecordDetailPanel" in source, "ArchiveTab must import ArchiveRecordDetailPanel"
    assert "ArchiveSyncPanel" in source, "ArchiveTab must import ArchiveSyncPanel"

    # /scheduler/plan-archive 참조 존재
    assert "/scheduler/plan-archive" in source, "ArchiveTab must reference /scheduler/plan-archive"


def test_archivetab_placeholder_text_visible(page: Page) -> None:
    _install_archive_tab_routes(page)
    page.goto(f"{ADMIN_URL}/automation?tab=plans&subtab=archive")
    page.wait_for_timeout(800)
    body_text = page.inner_text("body")
    assert (
        "archive 파일" in body_text
        or "schedule 운영" in body_text
        or "plan-archive" in body_text.lower()
        or "이 화면은" in body_text
    ), f"placeholder text not found in ArchiveTab; body: {body_text[:400]}"


def test_archivetab_redirect_banner_on_runner_query(page: Page) -> None:
    _install_archive_tab_routes(page)
    page.goto(f"{ADMIN_URL}/automation?tab=plans&subtab=archive&runner=plan-archive-schedule")
    page.wait_for_timeout(800)
    body_text = page.inner_text("body")
    assert (
        "plan-archive" in body_text.lower()
        or "scheduler" in body_text.lower()
        or "이동" in body_text
    ), f"redirect banner not found for runner query; body: {body_text[:400]}"


def test_archivetab_no_auto_redirect(page: Page) -> None:
    _install_archive_tab_routes(page)
    page.goto(f"{ADMIN_URL}/automation?tab=plans&subtab=archive&runner=plan-archive-schedule")
    page.wait_for_timeout(1000)
    # 자동 redirect가 일어났다면 URL이 /scheduler/plan-archive로 바뀜
    assert "/scheduler/plan-archive" not in page.url, (
        f"ArchiveTab auto-redirected to {page.url}; should NOT auto-redirect"
    )


def test_archivetab_residual_components_source_present():
    """ArchiveRetrievalPanel, ArchiveRecordDetailPanel, ArchiveSyncPanel 파일이 존재한다."""
    base = Path(
        r"D:\work\project\tools\monitor-page\frontend\src\routes\plans\archive-tab"
    )
    for name in ("ArchiveRetrievalPanel.svelte", "ArchiveRecordDetailPanel.svelte", "ArchiveSyncPanel.svelte"):
        assert (base / name).exists(), f"Residual component file missing: {name}"
