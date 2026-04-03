"""Backward-compatible shim for deprecated merge_workflow module.

Many legacy tests and paths still import `merge_workflow` directly.
The implementation moved to `scripts/_deprecated/merge_workflow.py`,
so this module re-exports the same public symbols.
"""

from _deprecated.merge_workflow import (  # noqa: F401
    MergeWorkflow,
    RUNNER_KEY_PREFIX,
    TestResult,
    WorkflowResult,
)

