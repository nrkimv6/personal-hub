from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.dev_runner.dummy_plan_lifecycle_helpers import DUMMY_PLAN_SENTINEL


_E2E_PATH = (
    Path(__file__).resolve().parents[1]
    / "e2e"
    / "frontend"
    / "test_dev_runner_real_dummy_plan_merge_e2e.py"
)


def _load_e2e_module():
    spec = importlib.util.spec_from_file_location("real_dummy_plan_e2e_contract", _E2E_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_dummy_plan_default_engine_is_claude(monkeypatch):
    monkeypatch.delenv("E2E_REAL_DEV_RUNNER_ENGINE", raising=False)
    mod = _load_e2e_module()

    assert mod.DEFAULT_REAL_RUNNER_ENGINE == "claude"
    assert mod.ENGINE == "claude"


def test_real_dummy_plan_payload_uses_claude_and_multiple_cycles(tmp_path, monkeypatch):
    monkeypatch.delenv("E2E_REAL_DEV_RUNNER_ENGINE", raising=False)
    monkeypatch.delenv("E2E_REAL_DEV_RUNNER_MAX_CYCLES", raising=False)
    mod = _load_e2e_module()
    repo = tmp_path / "repo"
    plan = repo / "docs" / "plan" / "dummy.md"

    payload = mod._build_run_payload(repo, plan)

    assert payload["engine"] == "claude"
    assert payload["fix_engine"] == "claude"
    assert payload["max_cycles"] >= 2
    assert payload["dry_run"] is False
    assert payload["worktree"] is True
    assert payload["test_repo_root"] == str(repo)


def test_render_dummy_plan_has_explicit_marker_commit_contract():
    mod = _load_e2e_module()

    text = mod._render_dummy_plan_text()

    assert "dummy-plan-playwright-marker.txt" in text
    assert DUMMY_PLAN_SENTINEL in text
    assert "Commit the marker file" in text
    assert "relative path `docs/plan/2026-05-21_test-real-dummy-plan.md`" in text
    assert "Do not edit the absolute plan path" in text
    assert "Report the marker path and commit hash" in text


def test_retry_plan_includes_previous_failure_evidence():
    mod = _load_e2e_module()
    evidence = {
        "attempt": 1,
        "runner_id": "t-real_dummy_plan-1234",
        "engine": "claude",
        "reason": "sentinel_timeout",
        "evidence": {
            "redis": {"exit_reason": "completed_with_remaining_tasks"},
            "recent": {"status_code": 200, "body": {"lines": ["completed_with_remaining_tasks"]}},
            "merge": {"status_code": 200, "body": {"status": "unknown"}},
        },
    }

    text = mod._render_dummy_plan_text(retry_evidence=evidence)

    assert "Previous attempt failure analysis" in text
    assert "sentinel_timeout" in text
    assert "completed_with_remaining_tasks" in text
    assert "Do not stop after analysis" in text
    assert "use the relative plan path in the runner worktree" in text
