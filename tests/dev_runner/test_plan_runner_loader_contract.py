"""_dr_plan_runner loader alias contract TC."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from tests.dev_runner._path_helpers import (
    get_plan_runner_entry_script_path,
    get_plan_runner_impl_script_path,
    load_plan_runner_module,
)


def test_loader_alias_right_shared_hook_target():
    """R: unique module name으로 로드해도 canonical alias가 patch 대상과 같은 객체를 본다."""
    plan_runner_mod = load_plan_runner_module("_dr_plan_runner_loader_contract", use_entry=True)

    import _dr_stream_cleanup as stream_cleanup

    sentinel = object()
    with patch.object(plan_runner_mod, "detect_merged_but_not_done", sentinel):
        resolved = stream_cleanup._resolve_hook(
            "detect_merged_but_not_done",
            stream_cleanup._DEFAULT_DETECT_MERGED_BUT_NOT_DONE,
        )

    assert sys.modules["_dr_plan_runner"] is plan_runner_mod
    assert resolved is sentinel


def test_loader_alias_boundary_repeat_load_single_namespace():
    """B: 같은 module_name으로 두 번 로드해도 namespace가 분리되지 않는다."""
    first = load_plan_runner_module("_dr_plan_runner_loader_contract_repeat", use_entry=True)
    second = load_plan_runner_module("_dr_plan_runner_loader_contract_repeat", use_entry=True)

    assert first is second
    assert sys.modules["_dr_plan_runner"] is second


def test_loader_alias_reference_entry_vs_impl_paths():
    """Re: entry shim 경로와 canonical impl 경로가 서로 다른 파일을 가리킨다."""
    entry_path = get_plan_runner_entry_script_path()
    impl_path = get_plan_runner_impl_script_path()

    assert entry_path.exists()
    assert impl_path.exists()
    assert entry_path != impl_path
    assert entry_path.name == "_dr_plan_runner.py"
    assert impl_path.parent.name == "plan_runner"


# ─────────────────────────────────────────────────────────────
# T5: plans-root plan 실행 시 PLAN_RUNNER_PROJECT_ROOT 계약
# ─────────────────────────────────────────────────────────────

def test_get_target_project_root_with_plan_runner_project_root_env(tmp_path):
    """T5/R: PLAN_RUNNER_PROJECT_ROOT 환경변수 설정 시 get_target_project_root()가
    plans storage root가 아닌 주입된 project root를 반환한다.

    실제 subprocess 실행 시 _make_plan_runner_env()는 PLAN_RUNNER_PROJECT_ROOT=PROJECT_ROOT를
    주입한다. get_target_project_root()는 이 env를 최우선으로 반환해야 한다.
    """
    # plans-root 구조 (plans storage 경로)
    project_root = tmp_path / "monitor-page"
    project_root.mkdir()
    plans_dir = project_root / ".worktrees" / "plans" / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    plan_file = plans_dir / "2026-04-24_test.md"
    plan_file.write_text("# Test Plan\n")

    # _dr_subprocess.py가 주입하는 PLAN_RUNNER_PROJECT_ROOT (= 실제 target project root)
    injected_project_root = project_root

    # scripts/plan_runner 경로를 sys.path에 추가
    scripts_dir = Path(__file__).parent.parent.parent / "scripts" / "plan_runner"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from _dr_process_utils import get_target_project_root

    # PLAN_RUNNER_PROJECT_ROOT가 주입된 환경에서 실행
    with patch.dict(os.environ, {"PLAN_RUNNER_PROJECT_ROOT": str(injected_project_root)}):
        result = get_target_project_root(str(plan_file))

    # plans storage root(.worktrees/plans)가 아닌 주입된 project_root 반환
    assert result == injected_project_root.resolve() or result == injected_project_root, (
        f"PLAN_RUNNER_PROJECT_ROOT 주입 시 target project root를 반환해야 함, 실제: {result}"
    )
    plans_root = project_root / ".worktrees" / "plans"
    assert result != plans_root, (
        f"plans storage root를 반환하면 안 됨: {result}"
    )


def test_get_target_project_root_detects_worktrees_without_env(tmp_path):
    """T5/R: PLAN_RUNNER_PROJECT_ROOT 없을 때 .worktrees/plans git root에서 .worktrees 직전 경로 반환.

    git rev-parse가 .worktrees/plans를 반환해도 .worktrees 직전(= project root)을 반환해야 함.
    """
    project_root = tmp_path / "monitor-page"
    project_root.mkdir()
    (project_root / ".git").mkdir()  # project root 판정용
    plans_dir = project_root / ".worktrees" / "plans" / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    plan_file = plans_dir / "2026-04-24_test.md"
    plan_file.write_text("# Test Plan\n")

    scripts_dir = Path(__file__).parent.parent.parent / "scripts" / "plan_runner"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from _dr_process_utils import get_target_project_root

    plans_git_root = project_root / ".worktrees" / "plans"
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = str(plans_git_root) + "\n"

    # PLAN_RUNNER_PROJECT_ROOT 없이, git이 plans root를 반환하는 상황
    env_without_root = {k: v for k, v in os.environ.items() if k != "PLAN_RUNNER_PROJECT_ROOT"}
    with patch.dict(os.environ, env_without_root, clear=True), \
         patch("subprocess.run", return_value=mock_result):
        result = get_target_project_root(str(plan_file))

    assert result == project_root, (
        f".worktrees/plans git root 입력 시 project_root({project_root}) 반환해야 함, 실제: {result}"
    )
