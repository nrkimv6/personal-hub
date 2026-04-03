"""
Phase T5: HTTP 통합 테스트 — POST /api/plans/{path}/done

main 머지 후 실행. 실제 Admin API 서버(port 8001) 기동 상태에서 테스트.
- POST /api/plans/{path}/done 200 응답 및 plan 파일 archive 이동 확인
- GET /api/plans/ 에서 해당 plan이 docs/archive/로 이동됐는지 응답 검증

계약 모드:
- 기본(호환): 운영 서버 버전 차이를 고려해 hard-fail/legacy fallback 모두 허용
- strict: DONE_API_CONTRACT_STRICT=1 일 때 hard-fail(success=false + no archive move)만 허용
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
STRICT_CONTRACT = os.environ.get("DONE_API_CONTRACT_STRICT", "").strip() == "1"


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


@pytest.mark.skipif(not _api_available(), reason="Admin API 서버(8001)가 응답하지 않음 — 서버 기동 후 실행")
@pytest.mark.skipif(STRICT_CONTRACT, reason="strict 모드에서는 strict 전용 케이스만 실행")
def test_done_resolver_error_contract_compat_E():
    """E(compat): docs/plan 외 경로 done 호출 시 hard-fail/legacy fallback 둘 다 허용."""
    fname = "2026-04-03_test-http-resolver-fail.md"
    src_dir = PLANS_DIR.parent / "tmp"
    src_dir.mkdir(parents=True, exist_ok=True)
    src_path = src_dir / fname
    archive_path = ARCHIVE_DIR / fname

    src_path.write_text(
        "# HTTP resolver fail test\n"
        "> 상태: 구현완료\n"
        "> 진행률: 1/1 (100%)\n"
        "\n"
        "- [x] task\n",
        encoding="utf-8",
    )
    try:
        encoded = base64.urlsafe_b64encode(str(src_path).encode()).decode()
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=60)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        if body.get("success") is False:
            assert "archive target resolve failed" in (body.get("message") or "")
            assert src_path.exists(), "resolver 실패 시 원본 파일이 유지되어야 함"
            assert not archive_path.exists(), "resolver 실패 시 archive 이동이 발생하면 안 됨"
        else:
            # 운영 중 서버가 레거시 fallback 동작일 수 있으므로 호환 경로를 허용
            assert archive_path.exists(), "fallback 성공 시 archive 파일이 생성되어야 함"
            assert not src_path.exists(), "fallback 성공 시 원본 파일은 제거되어야 함"
    finally:
        if src_path.exists():
            src_path.unlink()
        if archive_path.exists():
            archive_path.unlink()


@pytest.mark.skipif(not _api_available(), reason="Admin API 서버(8001)가 응답하지 않음 — 서버 기동 후 실행")
@pytest.mark.skipif(not STRICT_CONTRACT, reason="DONE_API_CONTRACT_STRICT=1 환경에서만 strict 계약 검증")
def test_done_resolver_error_contract_strict_E():
    """E(strict): docs/plan 외 경로 done 호출은 hard-fail(success=false, no move)이어야 한다."""
    fname = "2026-04-03_test-http-resolver-fail-strict.md"
    src_dir = PLANS_DIR.parent / "tmp"
    src_dir.mkdir(parents=True, exist_ok=True)
    src_path = src_dir / fname
    archive_path = ARCHIVE_DIR / fname

    src_path.write_text(
        "# HTTP resolver fail strict test\n"
        "> 상태: 구현완료\n"
        "> 진행률: 1/1 (100%)\n"
        "\n"
        "- [x] task\n",
        encoding="utf-8",
    )
    try:
        encoded = base64.urlsafe_b64encode(str(src_path).encode()).decode()
        resp = requests.post(f"{BASE_URL}/plans/{encoded}/done", timeout=60)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("success") is False
        assert "archive target resolve failed" in (body.get("message") or "")
        assert src_path.exists(), "strict 모드에서는 원본 plan이 유지되어야 함"
        assert not archive_path.exists(), "strict 모드에서는 archive 이동이 발생하면 안 됨"
    finally:
        if src_path.exists():
            src_path.unlink()
        if archive_path.exists():
            archive_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
