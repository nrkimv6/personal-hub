"""
Phase T5: HTTP 통합 테스트 — POST /api/plans/{path}/done

main 머지 후 실행. 실제 Admin API 서버(port 8001) 기동 상태에서 테스트.
- POST /api/plans/{path}/done 200 응답 및 plan 파일 archive 이동 확인
- GET /api/plans/ 에서 해당 plan이 docs/archive/로 이동됐는지 응답 검증
"""
import base64
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("ADMIN_API_BASE", "http://localhost:8001/api/v1/dev-runner")
PLANS_DIR = Path(__file__).parent.parent.parent / "docs" / "plan"
ARCHIVE_DIR = Path(__file__).parent.parent.parent / "docs" / "archive"


def _api_available() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/plans", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def tmp_plan_file():
    """테스트용 임시 plan 파일 생성 (docs/plan/ 아래에 배치)"""
    fname = "2026-03-09_test-http-done-temp.md"
    path = PLANS_DIR / fname
    path.write_text(
        "# HTTP 테스트용 임시 plan\n"
        "> 상태: 구현중\n"
        "> 진행률: 2/2 (100%)\n"
        "\n"
        "- [x] task 1\n"
        "- [x] task 2\n",
        encoding="utf-8",
    )
    yield str(path)
    # 혹시 archive로 못 이동됐으면 정리
    if path.exists():
        path.unlink()
    archive_path = ARCHIVE_DIR / fname
    if archive_path.exists():
        archive_path.unlink()


@pytest.mark.skipif(not _api_available(), reason="Admin API 서버(8001)가 응답하지 않음 — 서버 기동 후 실행")
def test_post_done_returns_200_R(tmp_plan_file):
    """R: POST /api/plans/{path}/done → 200 응답"""
    encoded = base64.urlsafe_b64encode(tmp_plan_file.encode()).decode()
    resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=120)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"


@pytest.mark.skipif(not _api_available(), reason="Admin API 서버(8001)가 응답하지 않음 — 서버 기동 후 실행")
def test_done_moves_file_to_archive_R(tmp_plan_file):
    """R: done 처리 후 plan 파일이 docs/archive/로 이동됨 (test_post_done_returns_200_R 이후 상태 검증)"""
    fname = Path(tmp_plan_file).name
    archive_path = ARCHIVE_DIR / fname
    # test_post_done_returns_200_R에서 done API가 성공했으면 파일이 archive에 있어야 함
    # 파일이 plan/ 에 아직 있으면 이 테스트에서 done 호출
    if Path(tmp_plan_file).exists():
        encoded = base64.urlsafe_b64encode(tmp_plan_file.encode()).decode()
        requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=120)
    assert archive_path.exists(), f"archive 파일이 없음: {archive_path}"
    assert not Path(tmp_plan_file).exists(), f"plan 파일이 아직 plan/ 에 있음: {tmp_plan_file}"


@pytest.mark.skipif(not _api_available(), reason="Admin API 서버(8001)가 응답하지 않음 — 서버 기동 후 실행")
def test_done_nonexistent_plan_returns_error_E():
    """E: 존재하지 않는 plan 경로 → 4xx 응답"""
    encoded = base64.urlsafe_b64encode(b"/nonexistent/path/to/plan.md").decode()
    resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=10)
    assert 400 <= resp.status_code < 500, f"expected 4xx, got {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
