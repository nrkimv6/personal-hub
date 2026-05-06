"""Helpers for restart-frontend validation diagnostics."""

from __future__ import annotations

import subprocess


RESTART_FRONTEND_LOCK_BUSY_TEXT = (
    "Frontend restart lock is busy; another restart is in progress"
)
VALIDATION_CONCURRENCY_HINT = (
    "[Validation Concurrency Error] Concurrent restart detected. "
    "Please run these tests sequentially. category=validation_concurrency"
)


def is_restart_frontend_lock_busy(result: subprocess.CompletedProcess[str]) -> bool:
    output = "\n".join([result.stdout or "", result.stderr or ""])
    return RESTART_FRONTEND_LOCK_BUSY_TEXT in output


def restart_frontend_failure_context(
    result: subprocess.CompletedProcess[str],
) -> str:
    context = (
        f"rc={result.returncode}\n"
        f"[stdout]\n{(result.stdout or '').strip() or '(no output)'}\n"
        f"[stderr]\n{(result.stderr or '').strip() or '(no output)'}"
    )
    if is_restart_frontend_lock_busy(result):
        context = f"{context}\n\n{VALIDATION_CONCURRENCY_HINT}"
    return context
