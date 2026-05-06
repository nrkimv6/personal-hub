"""Facade for stream output implementation.

Tests patch `_dr_stream_output.*` from the scripts root.
"""

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "plan_runner"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from _dr_stream_output import *  # noqa: F401,F403
