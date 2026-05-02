import subprocess

from tests.helpers.restart_frontend_validation import (
    RESTART_FRONTEND_LOCK_BUSY_TEXT,
    VALIDATION_CONCURRENCY_HINT,
    restart_frontend_failure_context,
)


def test_restart_frontend_failure_context_includes_lock_busy_concurrency_hint():
    result = subprocess.CompletedProcess(
        args=["python", "browser_workers.py", "restart-frontend"],
        returncode=1,
        stdout="",
        stderr=RESTART_FRONTEND_LOCK_BUSY_TEXT,
    )

    context = restart_frontend_failure_context(result)

    assert "rc=1" in context
    assert RESTART_FRONTEND_LOCK_BUSY_TEXT in context
    assert VALIDATION_CONCURRENCY_HINT in context


def test_restart_frontend_failure_context_keeps_plain_failures_plain():
    result = subprocess.CompletedProcess(
        args=["python", "browser_workers.py", "restart-frontend"],
        returncode=1,
        stdout="plain stdout",
        stderr="plain stderr",
    )

    context = restart_frontend_failure_context(result)

    assert "plain stdout" in context
    assert "plain stderr" in context
    assert VALIDATION_CONCURRENCY_HINT not in context
