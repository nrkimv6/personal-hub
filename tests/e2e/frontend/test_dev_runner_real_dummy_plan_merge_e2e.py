from __future__ import annotations

import os
import json
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import redis as redis_lib
from playwright.sync_api import Page, expect

from tests.dev_runner.dummy_plan_lifecycle_helpers import DUMMY_PLAN_SENTINEL


pytestmark = [pytest.mark.e2e, pytest.mark.http_live, pytest.mark.timeout(240)]

BASE_API = os.environ.get("E2E_API_URL", "http://localhost:8001")
ENGINE = os.environ.get("E2E_REAL_DEV_RUNNER_ENGINE", "codex")
RUNNER_KEY_PREFIX = "plan-runner:runners"
TERMINAL_FAILURE_TOKENS = (
    "[FAILURE]",
    "completed_with_remaining_tasks",
    "REAL_RUNNER_ENV_UNAVAILABLE",
    "rate_limit",
    "auth failure",
)


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} - admin E2E 스킵")


def _run_git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"git {' '.join(args)} failed\nstdout={result.stdout}\nstderr={result.stderr}"


def _init_isolated_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "real-runner-repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.name", "real-runner-e2e")
    _run_git(repo, "config", "user.email", "real-runner-e2e@example.invalid")
    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / "2026-05-21_test-real-dummy-plan.md"
    plan.write_text(
        "\n".join(
            [
                "# test: real dummy plan",
                "",
                "> 상태: 구현중",
                "> branch:",
                "> worktree:",
                "> worktree-owner:",
                "",
                "## TODO",
                "",
                "- [ ] Create `dummy-plan-playwright-marker.txt` containing `DUMMY_PLAN_PLAYWRIGHT_SENTINEL`.",
                "- [ ] Commit the marker on the runner branch.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _run_git(repo, "add", "docs/plan/2026-05-21_test-real-dummy-plan.md")
    _run_git(repo, "commit", "-m", "test: add real dummy plan")
    return repo, plan


def _poll(timeout_seconds: float, interval_seconds: float, fn):
    deadline = time.monotonic() + timeout_seconds
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval_seconds)
    return last


def _cleanup_runner(client: httpx.Client, runner_id: str) -> None:
    for method, path in (
        ("POST", f"/api/v1/dev-runner/runners/{runner_id}/stop"),
        ("DELETE", f"/api/v1/dev-runner/runners/{runner_id}/worktree"),
        ("DELETE", f"/api/v1/dev-runner/runners/{runner_id}/tab"),
    ):
        try:
            client.request(method, path, timeout=10.0)
        except Exception:
            pass


def _redis_runner_evidence(runner_id: str) -> dict:
    try:
        redis_client = redis_lib.Redis(decode_responses=True)
        prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"
        fields = {
            name: redis_client.get(f"{prefix}:{name}")
            for name in (
                "status",
                "exit_reason",
                "merge_status",
                "merge_message",
                "error",
                "plan_file",
                "stream_log_path",
                "log_file_path",
                "branch",
                "worktree_path",
                "test_source",
            )
        }
        recent_meta = redis_client.get(f"plan-runner:recent-meta:{runner_id}")
        if recent_meta:
            try:
                fields["recent_meta"] = json.loads(recent_meta)
            except json.JSONDecodeError:
                fields["recent_meta"] = recent_meta
        redis_client.close()
        return {key: value for key, value in fields.items() if value}
    except Exception as exc:
        return {"redis_error": repr(exc)}


def _tail_lines(lines: list[str], limit: int = 20) -> list[str]:
    return [line[:500] for line in lines[-limit:]]


def _runner_evidence(client: httpx.Client, runner_id: str) -> dict:
    evidence: dict = {"runner_id": runner_id, "redis": _redis_runner_evidence(runner_id)}
    for label, path, params in (
        ("recent", "/api/v1/dev-runner/logs/recent", {"runner_id": runner_id, "lines": 300}),
        ("full", "/api/v1/dev-runner/logs/full", {"runner_id": runner_id, "offset": 0, "limit": 1000}),
        ("merge", f"/api/v1/dev-runner/merge/{runner_id}", None),
    ):
        try:
            response = client.get(path, params=params)
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("lines"), list):
                body = {**body, "lines": _tail_lines(body["lines"])}
            evidence[label] = {"status_code": response.status_code, "body": body}
        except Exception as exc:
            evidence[label] = {"error": repr(exc)}
    return evidence


def test_real_dummy_plan_runner_merges_isolated_repo_from_admin_ui(page: Page, frontend_url: str, system_mode: str, tmp_path):
    _skip_admin_mode_if_public(system_mode)
    repo, plan = _init_isolated_repo(Path(tmp_path))
    runner_id = None

    page.goto(f"{frontend_url}/automation?tab=dev-runner")
    payload = {
        "plan_file": str(plan),
        "test_source": "real_dummy_plan_playwright",
        "test_repo_root": str(repo),
        "engine": ENGINE,
        "fix_engine": ENGINE,
        "dry_run": False,
        "worktree": True,
        "max_cycles": 1,
    }
    response = page.evaluate(
        """async (payload) => {
            const res = await fetch('/api/v1/dev-runner/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const text = await res.text();
            return {status: res.status, text};
        }""",
        payload,
    )
    assert response["status"] == 200, (
        "REAL_RUNNER_ENV_UNAVAILABLE: dev-runner real run was not accepted; "
        f"status={response['status']} body={response['text']}"
    )
    accepted = json.loads(response["text"])
    runner_id = accepted["runner_id"]

    with httpx.Client(base_url=BASE_API, timeout=10.0) as client:
        try:
            def read_sentinel():
                recent = client.get("/api/v1/dev-runner/logs/recent", params={"runner_id": runner_id, "lines": 300})
                if recent.status_code == 200:
                    lines = recent.json().get("lines", [])
                    if any(DUMMY_PLAN_SENTINEL in line for line in lines):
                        return {"source": "recent", "lines": lines}
                    if any(token in line for token in TERMINAL_FAILURE_TOKENS for line in lines):
                        return {"source": "recent", "failed": True, "evidence": _runner_evidence(client, runner_id)}
                full = client.get("/api/v1/dev-runner/logs/full", params={"runner_id": runner_id, "offset": 0, "limit": 1000})
                if full.status_code == 200:
                    lines = full.json().get("lines", [])
                    if any(DUMMY_PLAN_SENTINEL in line for line in lines):
                        return {"source": "full", "lines": lines}
                    if any(token in line for token in TERMINAL_FAILURE_TOKENS for line in lines):
                        return {"source": "full", "failed": True, "evidence": _runner_evidence(client, runner_id)}
                return None

            sentinel = _poll(120.0, 5.0, read_sentinel)
            assert sentinel and not sentinel.get("failed"), (
                "sentinel missing or runner failed "
                f"runner_id={runner_id} evidence="
                f"{json.dumps(_runner_evidence(client, runner_id), ensure_ascii=False)[:5000]}"
            )

            def read_merged():
                merge = client.get(f"/api/v1/dev-runner/merge/{runner_id}")
                if merge.status_code == 200 and merge.json().get("status") == "merged":
                    return merge.json()
                runners = client.get("/api/v1/dev-runner/runners", params={"include_hidden": "true"})
                if runners.status_code == 200:
                    for item in runners.json():
                        if item.get("runner_id") == runner_id and item.get("merge_status") == "merged":
                            return item
                return None

            merged = _poll(120.0, 5.0, read_merged)
            assert merged, (
                "merged terminal state missing "
                f"runner_id={runner_id} evidence="
                f"{json.dumps(_runner_evidence(client, runner_id), ensure_ascii=False)[:5000]}"
            )

            page.goto(f"{frontend_url}/automation?tab=dev-runner&runner={runner_id}")
            expect(page.get_by_text(DUMMY_PLAN_SENTINEL)).to_be_visible(timeout=30000)
            expect(page.get_by_text("merged").or_(page.get_by_text("머지됨")).first).to_be_visible(timeout=30000)

            marker = repo / "dummy-plan-playwright-marker.txt"
            assert marker.exists(), f"isolated repo marker missing runner_id={runner_id} merge={merged}"
            assert not (Path(__file__).resolve().parents[3] / marker.name).exists()
        finally:
            if runner_id:
                _cleanup_runner(client, runner_id)
