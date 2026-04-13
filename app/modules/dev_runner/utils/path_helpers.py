"""dev_runner 모듈에서 사용하는 스크립트 경로 유틸리티."""

from __future__ import annotations

import os
from pathlib import Path


def get_repo_root() -> Path:
    """현재 monitor-page 레포지토리 루트 경로 반환."""
    # app/modules/dev_runner/utils/path_helpers.py -> app/modules/dev_runner/utils -> app/modules/dev_runner -> app/modules -> app -> root
    return Path(__file__).resolve().parents[4]


def get_plan_runner_dir() -> Path:
    """scripts/plan_runner 디렉토리 경로 반환."""
    return get_repo_root() / "scripts" / "plan_runner"


def get_listener_script_path() -> Path:
    """dev-runner-command-listener.py 스크립트 경로 반환."""
    return get_plan_runner_dir() / "dev-runner-command-listener.py"


def get_plan_runner_script_path() -> Path:
    """_dr_plan_runner.py 스크립트 경로 반환."""
    return get_plan_runner_dir() / "_dr_plan_runner.py"
