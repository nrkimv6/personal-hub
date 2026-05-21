from __future__ import annotations

import json
import os
import base64
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import redis as redis_lib
from playwright.sync_api import Page

from tests.dev_runner.dummy_plan_lifecycle_helpers import DUMMY_PLAN_SENTINEL


pytestmark = [pytest.mark.e2e, pytest.mark.http_live, pytest.mark.timeout(600)]

BASE_API = os.environ.get("E2E_API_URL", "http://localhost:8001")
DEFAULT_REAL_RUNNER_ENGINE = "claude"
ENGINE = os.environ.get("E2E_REAL_DEV_RUNNER_ENGINE", DEFAULT_REAL_RUNNER_ENGINE)
MAX_CYCLES = int(os.environ.get("E2E_REAL_DEV_RUNNER_MAX_CYCLES", "2"))
MAX_ATTEMPTS = int(os.environ.get("E2E_REAL_DEV_RUNNER_MAX_ATTEMPTS", "2"))
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=2.0)
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


def _run_git_text(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"git {' '.join(args)} failed\nstdout={result.stdout}\nstderr={result.stderr}"
    return result.stdout.strip()


def _tail_lines(lines: list[str], limit: int = 20) -> list[str]:
    return [line[:500] for line in lines[-limit:]]


def _compact_log_body(value):
    if not isinstance(value, dict):
        return value
    body = value.get("body")
    if isinstance(body, dict) and isinstance(body.get("lines"), list):
        return {"status_code": value.get("status_code"), "lines": _tail_lines(body["lines"], limit=12)}
    return value


def _compact_evidence_for_plan(evidence: dict) -> dict:
    return {
        "attempt": evidence.get("attempt"),
        "runner_id": evidence.get("runner_id"),
        "engine": evidence.get("engine"),
        "reason": evidence.get("reason"),
        "redis": (evidence.get("evidence") or {}).get("redis") or evidence.get("redis"),
        "recent": _compact_log_body((evidence.get("evidence") or {}).get("recent")),
        "full": _compact_log_body((evidence.get("evidence") or {}).get("full")),
        "merge": (evidence.get("evidence") or {}).get("merge"),
    }


def _render_dummy_plan_text(*, retry_evidence: dict | None = None) -> str:
    lines = [
        "# test: real dummy plan",
        "",
        "> 상태: 구현중",
        "> branch:",
        "> worktree:",
        "> worktree-owner:",
        "> 진행률: 0/4 (0%)",
        "",
        "## Goal",
        "",
        "Create exactly one repository-root file named `dummy-plan-playwright-marker.txt`.",
        f"The file content must contain `{DUMMY_PLAN_SENTINEL}`.",
        "Commit the marker file on the runner branch with a normal git commit.",
        "Update this plan file only through the runner worktree relative path `docs/plan/2026-05-21_test-real-dummy-plan.md`.",
        "Do not edit the absolute plan path outside the current working tree.",
        "Mark the TODO checkboxes complete only in that relative plan file after the marker file exists.",
        "Commit the marker file and the relative plan file together on the runner branch.",
        "End the final response with the exact plan-runner result block below.",
        "Use the real marker commit hash in COMMITS.",
        "",
        "===AUTO-IMPL-RESULT===",
        "PROJECT: real-runner-repo",
        "TASK: create dummy plan marker",
        "STATUS: SUCCESS",
        "COMMITS: <marker commit hash>",
        "===END===",
        "",
    ]
    if retry_evidence:
        lines.extend(
            [
                "## Previous attempt failure analysis",
                "",
                "The previous real runner attempt did not reach the required sentinel/merge evidence.",
                "Before making changes, inspect this failure evidence and correct the missing step.",
                "Do not stop after analysis; create the marker file, commit it, and complete the checklist.",
                "If a previous attempt edited the absolute plan path, ignore that path and use the relative plan path in the runner worktree.",
                "",
                "```json",
                json.dumps(_compact_evidence_for_plan(retry_evidence), ensure_ascii=False, indent=2)[:4000],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## TODO",
            "",
            "- [ ] Inspect the repository root and confirm the marker file is absent.",
            f"- [ ] Create `dummy-plan-playwright-marker.txt` containing `{DUMMY_PLAN_SENTINEL}`.",
            "- [ ] Commit the marker on the runner branch.",
            "- [ ] Report the marker path and commit hash in the runner output.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_dummy_plan(plan: Path, *, retry_evidence: dict | None = None) -> None:
    plan.write_text(_render_dummy_plan_text(retry_evidence=retry_evidence), encoding="utf-8")


def _commit_if_dirty(repo: Path, message: str) -> None:
    status = _run_git_text(repo, "status", "--porcelain")
    if not status:
        return
    _run_git(repo, "add", "--", ".")
    _run_git(repo, "commit", "-m", message)


def _init_isolated_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "real-runner-repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.name", "real-runner-e2e")
    _run_git(repo, "config", "user.email", "real-runner-e2e@example.invalid")
    plan_dir = repo / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / "2026-05-21_test-real-dummy-plan.md"
    _write_dummy_plan(plan)
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


def _build_run_payload(repo: Path, plan: Path, *, engine: str = ENGINE, max_cycles: int = MAX_CYCLES) -> dict:
    return {
        "plan_file": str(plan),
        "test_source": "real_dummy_plan_playwright",
        "test_repo_root": str(repo),
        "engine": engine,
        "fix_engine": engine,
        "dry_run": False,
        "worktree": True,
        "max_cycles": max_cycles,
    }


def _encoded_plan_path(plan_file: str) -> str:
    return base64.urlsafe_b64encode(plan_file.encode("utf-8")).decode("ascii").rstrip("=")


def _is_releasable_test_claim_conflict(status: int, body_text: str, payload: dict) -> bool:
    if status != 409 or not payload.get("test_source") or not payload.get("plan_file"):
        return False
    try:
        detail = json.loads(body_text).get("detail", {})
    except json.JSONDecodeError:
        return False
    return isinstance(detail, dict) and detail.get("claim_state") == "queued"


def _release_test_claim(client: httpx.Client, plan_file: str) -> None:
    client.delete(f"/api/v1/dev-runner/plans/{_encoded_plan_path(plan_file)}/claim")


def _start_real_runner(page: Page, client: httpx.Client, payload: dict) -> str:
    response = None
    for attempt in range(1, 4):
        response = page.evaluate(
            """async (payload) => {
                const res = await fetch('/api/v1/dev-runner/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'x-api-gate-bypass': '1'},
                    body: JSON.stringify(payload),
                });
                const text = await res.text();
                return {status: res.status, text};
            }""",
            payload,
        )
        if not _is_releasable_test_claim_conflict(response["status"], response["text"], payload):
            break
        _release_test_claim(client, payload["plan_file"])
        time.sleep(float(attempt))
    assert response is not None
    assert response["status"] == 200, (
        "REAL_RUNNER_ENV_UNAVAILABLE: dev-runner real run was not accepted; "
        f"engine={payload.get('engine')} status={response['status']} body={response['text']}"
    )
    accepted = json.loads(response["text"])
    return accepted["runner_id"]


def _poll_attempt_result(client: httpx.Client, runner_id: str, *, attempt: int, engine: str) -> dict:
    def read_sentinel():
        try:
            recent = client.get("/api/v1/dev-runner/logs/recent", params={"runner_id": runner_id, "lines": 300})
            if recent.status_code == 200:
                lines = recent.json().get("lines", [])
                if any(DUMMY_PLAN_SENTINEL in line for line in lines):
                    return {"success": True, "source": "recent", "lines": lines}
                if any(token in line for token in TERMINAL_FAILURE_TOKENS for line in lines):
                    return {
                        "success": False,
                        "attempt": attempt,
                        "engine": engine,
                        "runner_id": runner_id,
                        "reason": "terminal_failure_token_recent",
                        "evidence": _runner_evidence(client, runner_id),
                    }
        except httpx.TimeoutException:
            return None

        try:
            full = client.get("/api/v1/dev-runner/logs/full", params={"runner_id": runner_id, "offset": 0, "limit": 1000})
            if full.status_code == 200:
                lines = full.json().get("lines", [])
                if any(DUMMY_PLAN_SENTINEL in line for line in lines):
                    return {"success": True, "source": "full", "lines": lines}
                if any(token in line for token in TERMINAL_FAILURE_TOKENS for line in lines):
                    return {
                        "success": False,
                        "attempt": attempt,
                        "engine": engine,
                        "runner_id": runner_id,
                        "reason": "terminal_failure_token_full",
                        "evidence": _runner_evidence(client, runner_id),
                    }
        except httpx.TimeoutException:
            return None
        return None

    sentinel = _poll(120.0, 5.0, read_sentinel)
    if not sentinel:
        return {
            "success": False,
            "attempt": attempt,
            "engine": engine,
            "runner_id": runner_id,
            "reason": "sentinel_timeout",
            "evidence": _runner_evidence(client, runner_id),
        }
    if not sentinel.get("success"):
        return sentinel

    def read_merged():
        try:
            merge = client.get(f"/api/v1/dev-runner/merge/{runner_id}")
            if merge.status_code == 200 and merge.json().get("status") == "merged":
                return merge.json()
            runners = client.get("/api/v1/dev-runner/runners", params={"include_hidden": "true"})
            if runners.status_code == 200:
                for item in runners.json():
                    if item.get("runner_id") == runner_id and item.get("merge_status") == "merged":
                        return item
        except httpx.TimeoutException:
            return None
        return None

    merged = _poll(120.0, 5.0, read_merged)
    if not merged:
        return {
            "success": False,
            "attempt": attempt,
            "engine": engine,
            "runner_id": runner_id,
            "reason": "merge_timeout",
            "evidence": _runner_evidence(client, runner_id),
        }
    return {
        "success": True,
        "attempt": attempt,
        "engine": engine,
        "runner_id": runner_id,
        "sentinel": sentinel,
        "merged": merged,
    }


def _run_real_runner_attempt(
    *,
    page: Page,
    client: httpx.Client,
    repo: Path,
    plan: Path,
    attempt: int,
    retry_evidence: dict | None,
) -> dict:
    if retry_evidence:
        _write_dummy_plan(plan, retry_evidence=retry_evidence)
        _commit_if_dirty(repo, f"test: retry real dummy plan attempt {attempt}")

    payload = _build_run_payload(repo, plan)
    runner_id = _start_real_runner(page, client, payload)
    result = _poll_attempt_result(client, runner_id, attempt=attempt, engine=payload["engine"])
    if not result.get("success"):
        _cleanup_runner(client, runner_id)
    return result


def _format_attempts_failure(attempts: list[dict]) -> str:
    return (
        "Claude real runner did not produce sentinel/merge evidence after self-rerun "
        f"attempts={json.dumps(attempts, ensure_ascii=False)[:9000]}"
    )


def test_claude_real_dummy_plan_runner_merges_isolated_repo_from_admin_ui_with_self_rerun(
    page: Page, frontend_url: str, system_mode: str, tmp_path
):
    _skip_admin_mode_if_public(system_mode)
    repo, plan = _init_isolated_repo(Path(tmp_path))

    page.goto(f"{frontend_url}/automation?tab=dev-runner")

    with httpx.Client(base_url=BASE_API, timeout=HTTP_TIMEOUT) as client:
        attempts: list[dict] = []
        retry_evidence = None
        success = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result = _run_real_runner_attempt(
                page=page,
                client=client,
                repo=repo,
                plan=plan,
                attempt=attempt,
                retry_evidence=retry_evidence,
            )
            attempts.append(result)
            if result.get("success"):
                success = result
                break
            retry_evidence = result

        assert success, _format_attempts_failure(attempts)

        runner_id = success["runner_id"]
        try:
            marker = repo / "dummy-plan-playwright-marker.txt"
            assert marker.exists(), f"isolated repo marker missing attempts={attempts}"
            assert DUMMY_PLAN_SENTINEL in marker.read_text(encoding="utf-8", errors="replace")
            assert not (Path(__file__).resolve().parents[3] / marker.name).exists()
        finally:
            _cleanup_runner(client, runner_id)
