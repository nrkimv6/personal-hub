"""dev_runner 테스트 경로 계산 공용 헬퍼."""

from __future__ import annotations

import sys
from pathlib import Path


def get_repo_root() -> Path:
    """tests/dev_runner 기준 현재 checkout의 repo root 반환."""
    return Path(__file__).resolve().parents[2]


def get_listener_script_path() -> Path:
    """현재 checkout의 listener 스크립트 경로 반환."""
    return get_repo_root() / "scripts" / "plan_runner" / "dev-runner-command-listener.py"


def get_plan_runner_script_path() -> Path:
    """현재 checkout의 plan_runner 스크립트 경로 반환."""
    return get_repo_root() / "scripts" / "plan_runner" / "_dr_plan_runner.py"


def get_project_python() -> str:
    """프로젝트 python 실행 경로 반환 (.venv 우선, 없으면 현재 인터프리터)."""
    venv_python = get_repo_root() / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def skip_if_missing(path: Path, label: str) -> None:
    """파일이 없으면 테스트를 skip한다."""
    if path.exists():
        return
    import pytest

    pytest.skip(f"{label} not found: {path}")
