"""dev_runner 경로 헬퍼 검증 TC."""

from __future__ import annotations

import inspect
import sys

import pytest

from tests.dev_runner import _path_helpers


def test_get_repo_root_right():
    """R: get_repo_root()는 현재 checkout 루트 경로를 반환해야 함."""
    repo_root = _path_helpers.get_repo_root()
    assert (repo_root / "scripts" / "plan_runner" / "dev-runner-command-listener.py").exists()
    assert (repo_root / ".git").exists()


def test_get_listener_script_path_right():
    """R: listener 경로는 helper로 구성되고 실제 파일이 존재해야 함."""
    listener_path = _path_helpers.get_listener_script_path()
    source = inspect.getsource(_path_helpers.get_listener_script_path)

    assert listener_path.exists()
    assert listener_path.name == "dev-runner-command-listener.py"
    assert "D:/work/project/tools/monitor-page" not in source


def test_get_plan_runner_entry_script_path_right():
    """R: entry shim 경로는 scripts/_dr_plan_runner.py를 가리켜야 함."""
    entry_path = _path_helpers.get_plan_runner_entry_script_path()

    assert entry_path.exists()
    assert entry_path.name == "_dr_plan_runner.py"
    assert entry_path.parent.name == "scripts"


def test_get_plan_runner_impl_script_path_right():
    """R: canonical impl 경로는 scripts/plan_runner/_dr_plan_runner.py를 가리켜야 함."""
    impl_path = _path_helpers.get_plan_runner_impl_script_path()

    assert impl_path.exists()
    assert impl_path.name == "_dr_plan_runner.py"
    assert impl_path.parent.name == "plan_runner"


def test_get_plan_runner_script_path_aliases_impl():
    """B: 기존 호환 helper는 canonical impl 경로를 그대로 반환해야 함."""
    assert _path_helpers.get_plan_runner_script_path() == _path_helpers.get_plan_runner_impl_script_path()


def test_get_project_python_boundary(monkeypatch, tmp_path):
    """B: .venv 경로가 없으면 sys.executable로 fallback해야 함."""
    monkeypatch.setattr(_path_helpers, "get_repo_root", lambda: tmp_path)

    resolved = _path_helpers.get_project_python()
    assert resolved == sys.executable


def test_skip_if_missing_error(tmp_path):
    """E: 파일 경로가 없으면 pytest.skip 예외를 발생시켜야 함."""
    missing_file = tmp_path / "no-listener.py"

    with pytest.raises(pytest.skip.Exception):
        _path_helpers.skip_if_missing(missing_file, "Listener script")
