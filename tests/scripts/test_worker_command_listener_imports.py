"""
worker-command-listener.py import bootstrap 회귀 TC

패치 전: ModuleNotFoundError: No module named 'app' (sys.path에 PROJECT_ROOT 누락)
패치 후: import 완료 후 --check-imports 플래그로 SystemExit(0) 즉시 종료

TC는 실제 subprocess + 실제 파일시스템 경로를 사용 (mock 없음).
Redis 서버 없이도 import 단계까지만 검증하므로 격리 환경에서 실행 가능.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
SCRIPT_PATH = REPO_ROOT / "scripts" / "services" / "worker-command-listener.py"


def _python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def test_worker_command_listener_check_imports_right():
    """repo root cwd에서 --check-imports 실행 → returncode 0."""
    result = subprocess.run(
        [_python(), str(SCRIPT_PATH), "--check-imports"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "import check ok" in result.stdout


def test_worker_command_listener_check_imports_boundary_script_dir_cwd():
    """cwd를 scripts/services/로 변경해도 동일 명령이 0 종료."""
    script_dir = REPO_ROOT / "scripts" / "services"
    result = subprocess.run(
        [_python(), str(SCRIPT_PATH), "--check-imports"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(script_dir),
        timeout=15,
    )
    assert result.returncode == 0, (
        f"cwd={script_dir}\nreturncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_worker_command_listener_check_imports_error_no_modulenotfound():
    """stderr/stdout에 ModuleNotFoundError: No module named 'app' 없음."""
    result = subprocess.run(
        [_python(), str(SCRIPT_PATH), "--check-imports"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
        timeout=15,
    )
    combined = result.stdout + result.stderr
    assert "ModuleNotFoundError: No module named 'app'" not in combined, (
        f"ModuleNotFoundError 발견\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_worker_command_listener_importlib_exec_right():
    """importlib.util.spec_from_file_location으로 스크립트 로드 → import 성공."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("worker_cmd_listener", str(SCRIPT_PATH))
    assert spec is not None, f"spec 생성 실패: {SCRIPT_PATH}"
    mod = importlib.util.module_from_spec(spec)
    # exec_module은 __main__ 블록을 실행하지 않으므로 BRPOP 루프 진입 없음
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass  # --check-imports 분기가 없으므로 발생하지 않음
    assert hasattr(mod, "main"), "main 함수 없음 — 로드 실패"
    assert hasattr(mod, "PROJECT_ROOT"), "PROJECT_ROOT 상수 없음 — bootstrap 누락"
