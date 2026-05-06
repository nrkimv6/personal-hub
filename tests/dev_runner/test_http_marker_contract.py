import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

HTTP_CONTRACT_FILES = [
    "tests/dev_runner/test_api_security.py",
    "tests/dev_runner/test_daily_report_api.py",
    "tests/dev_runner/test_listener_restart_73.py",
    "tests/dev_runner/test_plan_runner_skip_only_termination_http.py",
    "tests/dev_runner/test_plan_service_sync.py",
    "tests/dev_runner/test_plans_add_project.py",
    "tests/dev_runner/test_runner_api_multi.py",
    "tests/dev_runner/test_workflow_http.py",
]

HTTP_LIVE_BOUNDARY_FILES = [
    "tests/dev_runner/test_connection_leak_http.py",
    "tests/dev_runner/test_sse_filter_http.py",
]

SERVICE_ONLY_FILES = [
    "tests/dev_runner/conftest.py",
    "tests/dev_runner/test_plans_api_schema.py",
]

pytestmark = pytest.mark.integration


def _collect_with_marker(marker: str, *paths: str) -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--collect-only",
            "-m",
            marker,
            *paths,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    output = "\n".join([result.stdout, result.stderr])
    assert result.returncode in (0, 5), output
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/")
    }


def test_http_contract_files_are_selected_by_http_marker():
    collected = _collect_with_marker("http", *HTTP_CONTRACT_FILES)

    for path in HTTP_CONTRACT_FILES:
        assert any(nodeid.startswith(f"{path}::") for nodeid in collected), path


def test_http_marker_excludes_live_and_service_only_dev_runner_files():
    collected = _collect_with_marker(
        "http",
        *HTTP_LIVE_BOUNDARY_FILES,
        *SERVICE_ONLY_FILES,
    )

    assert collected == set()
