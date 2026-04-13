"""_dr_plan_runner loader alias contract TC."""

from __future__ import annotations

import sys
from unittest.mock import patch

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
