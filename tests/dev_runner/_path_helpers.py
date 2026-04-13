"""dev_runner 테스트 경로 계산 공용 헬퍼."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_PLAN_RUNNER_DIR = _SCRIPTS_DIR / "plan_runner"
for _path in (_SCRIPTS_DIR, _PLAN_RUNNER_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    import _dr_state  # noqa: F401
except Exception:
    pass


def get_repo_root() -> Path:
    """tests/dev_runner 기준 현재 checkout의 repo root 반환."""
    return Path(__file__).resolve().parents[2]


def get_listener_script_path() -> Path:
    """현재 checkout의 listener 스크립트 경로 반환."""
    return get_repo_root() / "scripts" / "plan_runner" / "dev-runner-command-listener.py"


def get_plan_runner_entry_script_path() -> Path:
    """현재 checkout의 compatibility shim 경로 반환."""
    return get_repo_root() / "scripts" / "_dr_plan_runner.py"


def get_plan_runner_impl_script_path() -> Path:
    """현재 checkout의 canonical plan_runner 구현 경로 반환."""
    return get_repo_root() / "scripts" / "plan_runner" / "_dr_plan_runner.py"


def get_plan_runner_script_path() -> Path:
    """기존 호환용 alias. 현재는 canonical impl 경로를 반환한다."""
    return get_plan_runner_impl_script_path()


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


def _load_module_from_path(module_name: str, script_path: Path, *, alias: str | None = None) -> ModuleType:
    """지정한 경로를 module_name으로 로드하고 필요 시 alias를 같이 등록한다."""
    existing = sys.modules.get(module_name)
    if existing is not None:
        if alias:
            sys.modules[alias] = existing
        return existing
    skip_if_missing(script_path, module_name)
    spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {script_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    if alias:
        sys.modules[alias] = mod
    return mod


def bootstrap_plan_runner_modules() -> tuple[ModuleType, ModuleType]:
    """_dr_state와 _dr_process_utils를 명시적으로 로드한다."""
    state_mod = importlib.import_module("_dr_state")
    process_utils_mod = importlib.import_module("_dr_process_utils")
    return state_mod, process_utils_mod


def load_plan_runner_module(module_name: str = "_dr_plan_runner", *, use_entry: bool = True) -> ModuleType:
    """plan-runner 모듈을 entry shim 또는 canonical impl 경로로 로드한다."""
    bootstrap_plan_runner_modules()
    script_path = (
        get_plan_runner_entry_script_path()
        if use_entry
        else get_plan_runner_impl_script_path()
    )
    alias = "_dr_plan_runner" if module_name != "_dr_plan_runner" else None
    return _load_module_from_path(module_name, script_path, alias=alias)


def load_listener_module(module_name: str = "dev_runner_command_listener") -> ModuleType:
    """listener 스크립트를 현재 checkout 기준으로 로드한다."""
    bootstrap_plan_runner_modules()
    return _load_module_from_path(module_name, get_listener_script_path())
