"""Compatibility shim for legacy imports/tests.

Actual implementation lives in scripts/plan_runner/_dr_plan_runner.py.
This shim executes the real source in the current module namespace so
monkeypatches against the loaded module affect the live globals.
"""

from pathlib import Path
import importlib
import sys

_IMPL_DIR = Path(__file__).resolve().parent / "plan_runner"
if str(_IMPL_DIR) not in sys.path:
    sys.path.insert(0, str(_IMPL_DIR))

importlib.import_module("_dr_state")

_IMPL_PATH = _IMPL_DIR / "_dr_plan_runner.py"
exec(compile(_IMPL_PATH.read_text(encoding="utf-8"), str(_IMPL_PATH), "exec"), globals())
