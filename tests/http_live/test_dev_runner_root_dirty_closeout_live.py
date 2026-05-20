import json
import os

import httpx
import pytest
import redis

from app.modules.dev_runner.services.redis_connection import RUNNER_KEY_PREFIX, REDIS_DB


pytestmark = pytest.mark.http_live

BASE_API = os.environ.get("E2E_API_URL", "http://localhost:8001")


def _runner_key(runner_id: str, suffix: str) -> str:
    return f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"


def _redis_client() -> redis.Redis:
    client = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.fail(f"Redis unavailable for live dev-runner merge status test: {exc}")
    return client


def _seed_merge_status(runner_id: str) -> dict[str, str]:
    summary = {
        "status": "reroute_required",
        "reason": "root_dirty_reroute_required",
        "affected_paths": ["tests/root-dirty-live.py"],
        "quarantine_diff_path": "logs/dev_runner/residue/root-dirty-closeout-live.diff",
        "reroute_required_path": "logs/dev_runner/reroute_required/root-dirty-closeout-live.md",
    }
    r = _redis_client()
    values = {
        "merge_status": "residue_blocked",
        "merge_reason": "root_dirty_reroute_required",
        "merge_message": "retry/direct merge result preserved reroute evidence",
        "quarantine_diff_path": summary["quarantine_diff_path"],
        "gate_evidence_summary": json.dumps(summary),
    }
    for suffix, value in values.items():
        r.set(_runner_key(runner_id, suffix), value, ex=300)
    return summary


def _cleanup_runner(runner_id: str) -> None:
    r = _redis_client()
    r.delete(*[
        _runner_key(runner_id, suffix)
        for suffix in (
            "merge_status",
            "merge_reason",
            "merge_message",
            "quarantine_diff_path",
            "gate_evidence_summary",
        )
    ])


def test_merge_status_preserves_reroute_required_paths_for_retry_or_direct_result():
    runner_id = "root-dirty-closeout-live"
    expected = _seed_merge_status(runner_id)
    try:
        response = httpx.get(f"{BASE_API}/api/v1/dev-runner/merge/{runner_id}", timeout=10.0)
        response.raise_for_status()
        body = response.json()

        assert body["status"] == "residue_blocked"
        assert body["reason"] == "root_dirty_reroute_required"
        assert body["quarantine_diff_path"] == expected["quarantine_diff_path"]
        assert body["gate_evidence_summary"]["status"] == "reroute_required"
        assert body["gate_evidence_summary"]["reroute_required_path"] == expected["reroute_required_path"]
    finally:
        _cleanup_runner(runner_id)
