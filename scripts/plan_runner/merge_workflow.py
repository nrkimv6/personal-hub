"""Backward-compatible shim for deprecated merge_workflow module.

Many legacy tests and paths still import `merge_workflow` directly.
The implementation moved to `scripts/_deprecated/merge_workflow.py`,
so this module re-exports the same public symbols.
"""

import sys as _sys_inject
from pathlib import Path as _Path_inject
_sys_inject.path.insert(0, str(_Path_inject(__file__).resolve().parent))
del _sys_inject, _Path_inject


from _deprecated.merge_workflow import (  # noqa: F401
    MergeWorkflow,
    RUNNER_KEY_PREFIX,
    TestResult,
    WorkflowResult,
)

