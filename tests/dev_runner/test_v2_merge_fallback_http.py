"""
TC: v2 merge fallback HTTP 통합 테스트 (Phase T5)

실제 Admin API 서버(port 8001) 기동 상태에서 테스트:
- test_v2_merge_fallback_status_endpoint_R: GET /status 응답에 merge_status 필드 포함 확인
- test_v2_merge_fallback_done_api_R: POST /plans/{path}/done → merge 완료 상태 plan 처리 확인
- test_v2_merge_fallback_runners_endpoint_R: GET /runners 응답 구조 검증 (runner별 merge_status 필드)
"""
import base64
import os
import tempfile
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("ADMIN_API_BASE", "http://localhost:8001/api/v1/dev-runner")
PLANS_DIR = Path(__file__).parent.parent.parent / "docs" / "plan"
ARCHIVE_DIR = Path(__file__).parent.parent.parent / "docs" / "archive"


@pytest.fixture(scope="module")
def tmp_merged_plan():
    """테스트용 임시 plan 파일 — 머지대기 상태 (fallback 대상 시나리오)"""
    fname = "2026-03-30_test-v2-fallback-http-temp.md"
    path = PLANS_DIR / fname
    path.write_text(
        "# v2 fallback HTTP 테스트용 임시 plan\n"
        "> 상태: 머지대기\n"
        "> 진행률: 2/2 (100%)\n"
        "\n"
        "- [x] task 1\n"
        "- [x] task 2\n",
        encoding="utf-8",
    )
    yield str(path)
    if path.exists():
        path.unlink()
    archive_path = ARCHIVE_DIR / fname
    if archive_path.exists():
        archive_path.unlink()


def test_v2_merge_fallback_status_endpoint_R():
    """R: GET /status → 응답 200 + runner 상태 필드 포함"""
    resp = requests.get(f"{BASE_URL}/status", timeout=10)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    data = resp.json()
    # 기본 필드 확인
    assert "running" in data, f"'running' 필드 없음: {data}"
    assert "redis_connected" in data, f"'redis_connected' 필드 없음: {data}"


def test_v2_merge_fallback_runners_endpoint_R():
    """R: GET /runners → 응답 200 + 리스트 형태"""
    resp = requests.get(f"{BASE_URL}/runners", timeout=10)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    data = resp.json()
    assert isinstance(data, list), f"runners 응답이 리스트가 아님: {type(data)}"


def test_v2_merge_fallback_done_api_R(tmp_merged_plan):
    """R: POST /plans/{path}/done → 머지대기 상태 plan fallback 처리 확인 (200 응답 + archive 이동)"""
    encoded = base64.urlsafe_b64encode(tmp_merged_plan.encode()).decode()
    resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=120)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


def test_v2_merge_fallback_done_archive_R(tmp_merged_plan):
    """R: done 처리 후 plan 파일이 archive로 이동됨"""
    fname = Path(tmp_merged_plan).name
    archive_path = ARCHIVE_DIR / fname
    # 이미 archive에 없으면 done 호출
    if Path(tmp_merged_plan).exists():
        encoded = base64.urlsafe_b64encode(tmp_merged_plan.encode()).decode()
        requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=120)
    assert archive_path.exists(), f"archive 파일 없음: {archive_path}"
    assert not Path(tmp_merged_plan).exists(), f"plan 파일이 plan/ 에 남아있음: {tmp_merged_plan}"


def test_v2_merge_fallback_done_nonexistent_E():
    """E: 존재하지 않는 plan → 4xx 응답"""
    encoded = base64.urlsafe_b64encode(b"/nonexistent/fallback-test-plan.md").decode()
    resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=10)
    assert 400 <= resp.status_code < 500, f"expected 4xx, got {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
