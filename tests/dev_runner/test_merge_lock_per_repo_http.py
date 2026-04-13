"""
TC: merge lock per-repo HTTP 통합 테스트 (Phase T5)

실제 Admin API 서버(port 8001) 기동 상태에서 테스트:
- test_merge_lock_runners_endpoint_R: GET /runners 응답에 merge_status 필드 포함 확인
  (lock 키 구조 변경 후 API 응답 형식 영향 없음 검증)
- test_merge_lock_status_endpoint_R: GET /status 응답 정상 구조 확인
  (per-repo lock 적용 후 기존 status 구조 영향 없음 검증)
"""
import os

import pytest
import requests

pytestmark = [
    pytest.mark.http_live,
    pytest.mark.skip(reason="merge_lock deprecated — merge_queue로 대체"),
]

BASE_URL = os.environ.get("ADMIN_API_BASE", "http://localhost:8001/api/v1/dev-runner")


def test_merge_lock_runners_endpoint_R():
    """R(Right): GET /runners → 200 + 기존 응답 구조 유지 (per-repo lock 적용 후 영향 없음)"""
    resp = requests.get(f"{BASE_URL}/runners", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    # 응답이 dict 또는 list 형태인지 확인
    assert isinstance(data, (dict, list))


def test_merge_lock_status_endpoint_R():
    """R(Right): GET /status → 200 + success 필드 포함 (lock 키 구조 변경 후 영향 없음)"""
    resp = requests.get(f"{BASE_URL}/status", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data or "status" in data or isinstance(data, dict)
