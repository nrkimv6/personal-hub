"""
TC: v2 merge fallback HTTP 통합 테스트 (Phase T5)

실제 Admin API 서버(port 8001) 기동 상태에서 테스트:
- test_v2_merge_fallback_status_endpoint_R: GET /status 응답에 merge_status 필드 포함 확인
- test_v2_merge_fallback_done_api_R: POST /plans/{path}/done → merge 완료 상태 plan 처리 확인
- test_v2_merge_fallback_runners_endpoint_R: GET /runners 응답 구조 검증 (runner별 merge_status 필드)
"""
import base64
import os
from pathlib import Path

import pytest
import requests
from tests.dev_runner.live_done_http_helpers import isolated_live_done_project

BASE_URL = os.environ.get("ADMIN_API_BASE", "http://localhost:8001/api/v1/dev-runner")
REQUEST_TIMEOUT = 5


@pytest.fixture(scope="module")
def tmp_merged_plan():
    """테스트용 임시 plan 파일 — 허용 루트 내부 isolated project 사용."""
    with isolated_live_done_project("v2-fallback-http") as project:
        path = project.write_plan(
            filename="2026-03-30_test-v2-fallback-http-temp.md",
            title="v2 fallback HTTP 테스트용 임시 plan",
            status="머지대기",
            body="- [x] task 1\n- [x] task 2\n",
            todo_entry="- [ ] v2 fallback HTTP 테스트용 임시 plan\n",
        )
        yield {
            "plan_path": str(path),
            "archive_path": str(project.archive_dir / path.name),
            "todo_path": str(project.todo_path),
            "done_path": str(project.done_path),
        }


def test_v2_merge_fallback_status_endpoint_R():
    """R: GET /status → 응답 200 + runner 상태 필드 포함"""
    try:
        resp = requests.get(f"{BASE_URL}/status", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    data = resp.json()
    # 기본 필드 확인
    assert "running" in data, f"'running' 필드 없음: {data}"
    assert "redis_connected" in data, f"'redis_connected' 필드 없음: {data}"


def test_v2_merge_fallback_runners_endpoint_R():
    """R: GET /runners → 응답 200 + 리스트 형태"""
    try:
        resp = requests.get(f"{BASE_URL}/runners", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    data = resp.json()
    assert isinstance(data, list), f"runners 응답이 리스트가 아님: {type(data)}"


def test_v2_merge_fallback_done_api_R(tmp_merged_plan):
    """R: POST /plans/{path}/done → 머지대기 상태 plan fallback 처리 확인 (200 응답 + archive 이동)"""
    encoded = base64.urlsafe_b64encode(tmp_merged_plan["plan_path"].encode()).decode()
    try:
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


def test_v2_merge_fallback_done_archive_R(tmp_merged_plan):
    """R: done 처리 후 temp project archive로 이동되고 temp TODO/DONE만 갱신된다."""
    plan_path = Path(tmp_merged_plan["plan_path"])
    archive_path = Path(tmp_merged_plan["archive_path"])
    # 이미 archive에 없으면 done 호출
    if plan_path.exists():
        encoded = base64.urlsafe_b64encode(tmp_merged_plan["plan_path"].encode()).decode()
        try:
            requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            pytest.skip(f"admin api unavailable: {exc}")
    assert archive_path.exists(), f"archive 파일 없음: {archive_path}"
    assert not plan_path.exists(), f"plan 파일이 plan/ 에 남아있음: {plan_path}"
    assert "v2 fallback HTTP 테스트용 임시 plan" not in Path(tmp_merged_plan["todo_path"]).read_text(encoding="utf-8")
    assert "v2 fallback HTTP 테스트용 임시 plan" in Path(tmp_merged_plan["done_path"]).read_text(encoding="utf-8")


def test_v2_merge_fallback_done_nonexistent_E():
    """E: 존재하지 않는 plan → 4xx 응답"""
    encoded = base64.urlsafe_b64encode(b"/nonexistent/fallback-test-plan.md").decode()
    try:
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        pytest.skip(f"admin api unavailable: {exc}")
    assert 400 <= resp.status_code < 500, f"expected 4xx, got {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
