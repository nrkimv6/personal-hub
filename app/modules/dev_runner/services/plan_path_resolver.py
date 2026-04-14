"""app 계층에서 scripts/_dr_plan_paths.py를 재사용하기 위한 브리지."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_PLAN_RUNNER_DIR = str(Path(__file__).resolve().parents[4] / "scripts" / "plan_runner")
if _SCRIPTS_PLAN_RUNNER_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_PLAN_RUNNER_DIR)

from _dr_plan_paths import (  # type: ignore
    PathResolution,
    PathRuleError,
    classify_plan_stage,
    is_archive_or_history_path,
    read_plan_status,
    resolve_plan_target,
)

__all__ = [
    "PathResolution",
    "PathRuleError",
    "classify_plan_stage",
    "is_archive_or_history_path",
    "read_plan_status",
    "resolve_plan_target",
]

