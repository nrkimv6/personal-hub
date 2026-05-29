"""Facade for dev-runner plan-runner helpers.

The implementation lives under `scripts/plan_runner/` to keep the scripts
namespace organized, but existing callers/tests import from `scripts/_dr_*`.
"""

import importlib.util
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "plan_runner"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

_IMPL_PATH = _BASE / "_dr_plan_runner.py"
_SPEC = importlib.util.spec_from_file_location("_monitor_page_dr_plan_runner_impl", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load plan-runner implementation: {_IMPL_PATH}")

_IMPL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

__all__ = [
    name
    for name in dir(_IMPL)
    if not (name.startswith("__") and name.endswith("__"))
]
globals().update({name: getattr(_IMPL, name) for name in __all__})
