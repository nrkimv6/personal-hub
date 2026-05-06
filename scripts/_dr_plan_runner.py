"""Facade for dev-runner plan-runner helpers.

The implementation lives under `scripts/plan_runner/` to keep the scripts
namespace organized, but existing callers/tests import from `scripts/_dr_*`.
"""

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "plan_runner"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from _dr_plan_runner import *  # noqa: F401,F403
