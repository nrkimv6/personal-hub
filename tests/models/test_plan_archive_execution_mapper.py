"""Mapper contracts for Plan Archive execution read models."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import configure_mappers

from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_isolated_python(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_plan_archive_execution_mapper_init_E_without_direct_claude_worker_import() -> None:
    result = _run_isolated_python(
        """
import sys
from sqlalchemy.orm import configure_mappers

assert "app.modules.claude_worker.models.llm_request" not in sys.modules
from app.models.plan_archive_execution import PlanArchiveExecutionAttempt, PlanArchiveExecutionJob
configure_mappers()
print(
    PlanArchiveExecutionJob.latest_request.property.mapper.class_.__name__,
    PlanArchiveExecutionAttempt.request.property.mapper.class_.__name__,
)
"""
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "LLMRequest LLMRequest" in result.stdout


def test_plan_archive_execution_mapper_init_R_relationship_resolves() -> None:
    configure_mappers()

    assert PlanArchiveExecutionJob.latest_request.property.mapper.class_.__name__ == "LLMRequest"


def test_plan_archive_execution_attempt_mapper_init_R_request_resolves() -> None:
    configure_mappers()

    assert PlanArchiveExecutionAttempt.request.property.mapper.class_.__name__ == "LLMRequest"


def test_plan_archive_execution_no_import_cycle_Co() -> None:
    result = _run_isolated_python(
        """
import importlib

module = importlib.import_module("app.modules.claude_worker.models.llm_request")
assert module.LLMRequest.__name__ == "LLMRequest"
print("ok")
"""
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout
