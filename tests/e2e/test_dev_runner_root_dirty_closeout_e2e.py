import json
import os
import time

import httpx
import pytest
import redis

from app.modules.dev_runner.services.redis_connection import (
    ACTIVE_RUNNERS_KEY,
    RECENT_RUNNERS_KEY,
    RUNNER_KEY_PREFIX,
    REDIS_DB,
)


pytestmark = [pytest.mark.e2e, pytest.mark.http_live]

BASE_API = os.environ.get("E2E_API_URL", "http://localhost:8001")


def _runner_key(runner_id: str, suffix: str) -> str:
    return f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"


def _redis_client() -> redis.Redis:
    client = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.fail(f"Redis unavailable for live dev-runner closeout test: {exc}")
    return client


def _seed_reroute_runner(runner_id: str) -> dict[str, str]:
    summary = {
        "status": "reroute_required",
        "reason": "root_dirty_reroute_required",
        "affected_paths": ["app/modules/example.py"],
        "quarantine_diff_path": "logs/dev_runner/residue/root-dirty-closeout-e2e.diff",
        "reroute_required_path": "logs/dev_runner/reroute_required/root-dirty-closeout-e2e.md",
    }
    r = _redis_client()
    r.srem(ACTIVE_RUNNERS_KEY, runner_id)
    r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})
    values = {
        "status": "stopped",
        "plan_file": "docs/plan/root-dirty-closeout-e2e.md",
        "engine": "codex",
        "trigger": "user",
        "exit_reason": "completed",
        "merge_status": "residue_blocked",
        "merge_reason": "root_dirty_reroute_required",
        "merge_message": "root dirty closeout requires reroute evidence",
        "quarantine_diff_path": summary["quarantine_diff_path"],
        "gate_evidence_summary": json.dumps(summary),
    }
    for suffix, value in values.items():
        r.set(_runner_key(runner_id, suffix), value, ex=300)
    return summary


def _cleanup_runner(runner_id: str) -> None:
    r = _redis_client()
    r.srem(ACTIVE_RUNNERS_KEY, runner_id)
    r.zrem(RECENT_RUNNERS_KEY, runner_id)
    keys = [_runner_key(runner_id, suffix) for suffix in (
        "status",
        "plan_file",
        "engine",
        "trigger",
        "exit_reason",
        "merge_status",
        "merge_reason",
        "merge_message",
        "quarantine_diff_path",
        "gate_evidence_summary",
    )]
    keys.append(f"plan-runner:recent-meta:{runner_id}")
    r.delete(*keys)


def _get_json(path: str) -> object:
    try:
        response = httpx.get(f"{BASE_API}{path}", timeout=10.0)
    except httpx.ConnectError as exc:
        pytest.fail(f"live API unavailable for dev-runner closeout test: {exc}")
    response.raise_for_status()
    return response.json()


def test_runner_list_exposes_reroute_required_closeout_evidence():
    runner_id = "root-dirty-closeout-e2e"
    expected = _seed_reroute_runner(runner_id)
    try:
        runners = _get_json("/api/v1/dev-runner/runners")
        runner = next(item for item in runners if item["runner_id"] == runner_id)

        assert runner["visible"] is True
        assert runner["merge_status"] == "residue_blocked"
        assert runner["merge_reason"] == "root_dirty_reroute_required"
        assert runner["gate_evidence_summary"]["status"] == "reroute_required"
        assert runner["gate_evidence_summary"]["reroute_required_path"] == expected["reroute_required_path"]
        assert runner["gate_evidence_summary"]["quarantine_diff_path"] == expected["quarantine_diff_path"]
    finally:
        _cleanup_runner(runner_id)


def test_runner_detail_preserves_reroute_required_closeout_evidence():
    runner_id = "root-dirty-closeout-detail-e2e"
    expected = _seed_reroute_runner(runner_id)
    try:
        runner = _get_json(f"/api/v1/dev-runner/runners/{runner_id}")

        assert runner["running"] is False
        assert runner["gate_evidence_summary"]["reason"] == "root_dirty_reroute_required"
        assert runner["gate_evidence_summary"]["reroute_required_path"] == expected["reroute_required_path"]
        assert runner["gate_evidence_summary"]["quarantine_diff_path"] == expected["quarantine_diff_path"]
    finally:
        _cleanup_runner(runner_id)
