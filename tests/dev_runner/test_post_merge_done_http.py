"""
Phase T5: HTTP 통합 테스트 — POST /api/plans/{path}/done

main 머지 후 실행. 실제 Admin API 서버(port 8001) 기동 상태에서 테스트.
- POST /api/plans/{path}/done 200 응답 및 plan 파일 archive 이동 확인
- GET /api/plans/ 에서 해당 plan이 plans worktree archive로 이동됐는지 응답 검증

계약 모드:
- 기본(호환): 운영 서버 버전 차이를 고려해 hard-fail/legacy fallback 모두 허용
- strict: DONE_API_CONTRACT_STRICT=1 일 때 hard-fail(success=false + no archive move)만 허용
"""
import base64
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.routes.plans import router as plans_router
from tests.dev_runner.live_done_http_helpers import isolated_live_done_project

BASE_URL = os.environ.get("ADMIN_API_BASE", "http://localhost:8001/api/v1/dev-runner")
STRICT_CONTRACT = os.environ.get("DONE_API_CONTRACT_STRICT", "").strip() == "1"
REQUEST_TIMEOUT = 5


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(plans_router, prefix="/api/v1/dev-runner")
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(scope="module")
def tmp_plan_file():
    """테스트용 임시 plan 파일 생성 (허용 루트 내부 isolated project 사용)."""
    with isolated_live_done_project("post-merge-done-http") as project:
        path = project.write_plan(
            filename="2026-03-09_test-http-done-temp.md",
            title="HTTP 테스트용 임시 plan",
            status="구현중",
            body="- [x] task 1\n- [x] task 2\n",
            todo_entry="- [ ] HTTP 테스트용 임시 plan\n",
        )
        yield {
            "plan_path": str(path),
            "archive_path": str(project.archive_dir / path.name),
            "todo_path": str(project.todo_path),
            "done_path": str(project.done_path),
            "project_root": str(project.root),
        }


def test_post_done_returns_200_R(tmp_plan_file):
    """R: POST /api/plans/{path}/done → 200 응답"""
    encoded = base64.urlsafe_b64encode(tmp_plan_file["plan_path"].encode()).decode()
    try:
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


def test_done_moves_file_to_archive_R(tmp_plan_file):
    """R: done 처리 후 temp project archive로 이동되고 temp TODO/DONE만 갱신된다."""
    plan_path = Path(tmp_plan_file["plan_path"])
    archive_path = Path(tmp_plan_file["archive_path"])
    # test_post_done_returns_200_R에서 done API가 성공했으면 파일이 archive에 있어야 함
    # 파일이 plan/ 에 아직 있으면 이 테스트에서 done 호출
    if plan_path.exists():
        encoded = base64.urlsafe_b64encode(tmp_plan_file["plan_path"].encode()).decode()
        try:
            requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            pytest.skip(f"admin api unavailable: {exc}")
    assert archive_path.exists(), f"archive 파일이 없음: {archive_path}"
    assert not plan_path.exists(), f"plan 파일이 아직 plan/ 에 있음: {plan_path}"
    assert "HTTP 테스트용 임시 plan" not in Path(tmp_plan_file["todo_path"]).read_text(encoding="utf-8")
    assert "HTTP 테스트용 임시 plan" in Path(tmp_plan_file["done_path"]).read_text(encoding="utf-8")


def test_done_nonexistent_plan_returns_error_E():
    """E: 존재하지 않는 plan 경로 → 4xx 응답"""
    encoded = base64.urlsafe_b64encode(b"/nonexistent/path/to/plan.md").decode()
    try:
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert 400 <= resp.status_code < 500, f"expected 4xx, got {resp.status_code}"


@pytest.mark.http
def test_done_http_returns_ownership_guard_reason_with_runner_header(client, tmp_path):
    """T5: runner header가 있으면 ownership_guard 실패 contract를 HTTP 응답으로 그대로 반환한다."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / "2026-04-21-http-ownership.md"
    plan_path.write_text(
        "# HTTP ownership guard test\n"
        "> 상태: 구현완료\n"
        "> 진행률: 1/1 (100%)\n"
        "\n"
        "- [x] task\n",
        encoding="utf-8",
    )
    encoded = base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("=")

    with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), \
         patch("app.modules.dev_runner.routes.plans.plan_service.run_done", new=AsyncMock(return_value={
             "success": False,
             "message": "runner ownership guard blocked auto-done",
             "reason": "ownership_guard",
             "output": None,
             "remaining_tasks": 0,
             "total_tasks": 1,
             "plan_status": "구현완료",
         })) as mock_run_done, \
         patch("app.modules.dev_runner.routes.plans.plan_service.list_plans", return_value=[]):
        resp = client.post(
            f"/api/v1/dev-runner/plans/{encoded}/done",
            headers={"X-Plan-Runner-Id": "runner-http"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["reason"] == "ownership_guard"
    assert "ownership guard" in body["message"]
    assert mock_run_done.await_args.kwargs["runner_id"] == "runner-http"


@pytest.mark.http
def test_done_http_without_runner_header_stays_manual_contract(client, tmp_path):
    """T5: header 없이 같은 endpoint를 호출하면 manual contract(None runner_id)를 유지한다."""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / "2026-04-21-http-manual.md"
    plan_path.write_text(
        "# HTTP manual done test\n"
        "> 상태: 구현완료\n"
        "> 진행률: 1/1 (100%)\n"
        "\n"
        "- [x] task\n",
        encoding="utf-8",
    )
    encoded = base64.urlsafe_b64encode(str(plan_path).encode("utf-8")).decode("ascii").rstrip("=")

    with patch("app.modules.dev_runner.routes.plans.plan_service.validate_path", return_value=True), \
         patch("app.modules.dev_runner.routes.plans.plan_service.run_done", new=AsyncMock(return_value={
             "success": True,
             "message": "완료 처리 성공",
             "output": None,
             "remaining_tasks": 0,
             "total_tasks": 1,
             "plan_status": "구현완료",
         })) as mock_run_done, \
         patch("app.modules.dev_runner.routes.plans.plan_service.list_plans", return_value=[]):
        resp = client.post(f"/api/v1/dev-runner/plans/{encoded}/done")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert mock_run_done.await_args.kwargs["runner_id"] is None


@pytest.mark.skipif(STRICT_CONTRACT, reason="strict 모드에서는 strict 전용 케이스만 실행")
def test_done_resolver_error_contract_compat_E():
    """E(compat): active plan root 밖 경로 done 호출 시 hard-fail/legacy fallback 둘 다 허용."""
    with isolated_live_done_project("resolver-compat-http") as project:
        src_path = project.write_plan(
            filename="2026-04-03_test-http-resolver-fail.md",
            title="HTTP resolver fail test",
            status="구현완료",
            body="- [x] task\n",
            subdir="docs/tmp",
        )
        archive_path = project.archive_dir / src_path.name
        encoded = base64.urlsafe_b64encode(str(src_path).encode()).decode()
        try:
            resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            pytest.skip(f"admin api unavailable: {exc}")
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        if body.get("success") is False:
            assert "archive target resolve failed" in (body.get("message") or "")
            assert src_path.exists(), "resolver 실패 시 원본 파일이 유지되어야 함"
            assert not archive_path.exists(), "resolver 실패 시 archive 이동이 발생하면 안 됨"
        else:
            assert archive_path.exists(), "fallback 성공 시 archive 파일이 생성되어야 함"
            assert not src_path.exists(), "fallback 성공 시 원본 파일은 제거되어야 함"


@pytest.mark.skipif(not STRICT_CONTRACT, reason="DONE_API_CONTRACT_STRICT=1 환경에서만 strict 계약 검증")
def test_done_resolver_error_contract_strict_E():
    """E(strict): active plan root 밖 경로 done 호출은 hard-fail(success=false, no move)이어야 한다."""
    with isolated_live_done_project("resolver-strict-http") as project:
        src_path = project.write_plan(
            filename="2026-04-03_test-http-resolver-fail-strict.md",
            title="HTTP resolver fail strict test",
            status="구현완료",
            body="- [x] task\n",
            subdir="docs/tmp",
        )
        archive_path = project.archive_dir / src_path.name
        encoded = base64.urlsafe_b64encode(str(src_path).encode()).decode()
        try:
            resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            pytest.skip(f"admin api unavailable: {exc}")
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("success") is False
        assert "archive target resolve failed" in (body.get("message") or "")
        assert src_path.exists(), "strict 모드에서는 원본 plan이 유지되어야 함"
        assert not archive_path.exists(), "strict 모드에서는 archive 이동이 발생하면 안 됨"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
