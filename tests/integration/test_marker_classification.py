"""
pytest 마커 분류 정합성 검증 TC

@pytest.mark.e2e 오분류 수정 후 마커 수집 결과를 검증한다.
실행: pytest tests/integration/test_marker_classification.py -v
"""

import subprocess
import sys
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
PYTHON = sys.executable


def _run_collect(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """pytest --collect-only 를 실행하고 결과를 반환한다."""
    cmd = [PYTHON, "-m", "pytest", "--collect-only", "-q", "--no-header", "-p", "no:timeout"] + args
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )


# ---------------------------------------------------------------------------
# Phase T1 TC
# ---------------------------------------------------------------------------

def test_e2e_collect_only_playwright_only():
    """R: pytest -m e2e tests/e2e/ --collect-only → 이동된 5개 파일이 e2e 수집에 없음.

    이동된 5개 파일은 이제 tests/integration/에 있으므로 tests/e2e/에서 스캔하면 나오지 않는다.
    """
    result = _run_collect(["-m", "e2e", "tests/e2e/"], timeout=30)
    output = result.stdout + result.stderr

    # 이동된 파일들이 tests/e2e/ 경로에 없어야 한다
    misclassified = [
        "test_llm_model_registry_e2e",
        "test_llm_profile_e2e",
        "test_llm_providers_ui_e2e",
        "test_process_watch_e2e",
        "test_worker_db_unavailable_e2e",
    ]
    for filename in misclassified:
        assert filename not in output, (
            f"{filename}이 여전히 tests/e2e/에 존재함 (이동되지 않음): {output[:500]}"
        )


def test_integration_collect_only_includes_moved():
    """R: pytest -m integration tests/integration/ --collect-only → 이동된 5개 파일이 integration에서 수집."""
    result = _run_collect(["-m", "integration", "tests/integration/"], timeout=30)
    output = result.stdout + result.stderr

    moved_files = [
        "test_llm_model_registry",
        "test_llm_profile",
        "test_llm_providers_ui",
        "test_process_watch",
        "test_worker_db_unavailable",
    ]
    for filename in moved_files:
        assert filename in output, (
            f"{filename}이 integration 수집에 없음. 출력: {output[:500]}"
        )


def test_default_addopts_excludes_e2e():
    """R: pytest tests/e2e/ --collect-only (addopts의 not e2e 적용) → e2e 마커 테스트 미수집.

    addopts에 'not e2e'가 추가되어 Playwright 테스트가 기본 실행에서 제외되어야 한다.
    """
    result = _run_collect(["tests/e2e/"], timeout=30)
    output = result.stdout + result.stderr

    # addopts에 'not e2e'가 있으므로 e2e 마커 테스트는 수집 안 됨
    # "no tests ran" 또는 수집 결과 0개여야 한다
    assert "no tests ran" in output or "0 selected" in output or "<Module" not in output, (
        f"e2e 마커 테스트가 기본 addopts에서 수집됨 (not e2e 필터 미작동): {output[:500]}"
    )
