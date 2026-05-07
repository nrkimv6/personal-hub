"""gate_evidence_summary contract tests for dev-runner read models."""

import json
import sys
from pathlib import Path

from app.modules.dev_runner.schemas import MergeStatusResponse, RunStatusResponse, RunnerListItem
from app.modules.dev_runner.services.event_payload import build_status_payload
from app.modules.dev_runner.services.executor_service import _build_gate_failure_detail

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _dr_constants import RUNNER_KEY_PREFIX  # noqa: E402
from _dr_merge_persistence import MergePersistence  # noqa: E402
from _dr_process_utils import _build_recent_runner_meta  # noqa: E402


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.lists = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def expire(self, key, ttl):
        return True

    def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def smembers(self, key):
        return {b"runner-1"}

    def zrange(self, key, start, end):
        return []


def test_merge_persistence_writes_gate_evidence_summary():
    redis = _FakeRedis()
    persistence = MergePersistence(redis, "runner-1")

    persistence.persist_result_metadata(
        {
            "success": False,
            "merge_status": "residue_blocked",
            "message": "merge blocked by residue",
            "post_merge_done": {
                "status": "skipped_residue",
                "reason": "residue_guard",
                "quarantine_diff_path": "logs/dev_runner/residue/runner.diff",
            },
        }
    )

    raw = redis.get(f"{RUNNER_KEY_PREFIX}:runner-1:gate_evidence_summary")
    summary = json.loads(raw)
    assert summary["tool"] == "merge-test"
    assert summary["reason"] == "residue_guard"
    assert summary["quarantine_diff_path"] == "logs/dev_runner/residue/runner.diff"


def test_event_payload_decodes_gate_evidence_summary():
    redis = _FakeRedis()
    prefix = f"{RUNNER_KEY_PREFIX}:runner-1"
    redis.set(f"{prefix}:status", "running")
    redis.set(f"{prefix}:plan_file", "docs/plan/example.md")
    redis.set(
        f"{prefix}:gate_evidence_summary",
        json.dumps({"reason": "restart_scheduled", "done_post_merge_status": "restart_scheduled"}),
    )

    payload = build_status_payload(redis, "runner-1")

    assert payload is not None
    assert payload["gate_evidence_summary"]["reason"] == "restart_scheduled"


def test_recent_runner_meta_preserves_gate_evidence_summary_as_json_text():
    redis = _FakeRedis()
    raw_summary = json.dumps({"reason": "service_lock", "status": "approval_required"}).encode("utf-8")
    redis.set(f"{RUNNER_KEY_PREFIX}:runner-1:gate_evidence_summary", raw_summary)

    meta = _build_recent_runner_meta(
        redis,
        "runner-1",
        trigger="user",
        plan_file="docs/plan/example.md",
    )

    assert json.loads(meta["gate_evidence_summary"])["reason"] == "service_lock"


def test_schema_and_http_error_detail_preserve_summary():
    summary = {"reason": "reserved_status", "target_partition": "blocked"}

    assert RunStatusResponse(running=False, gate_evidence_summary=summary).gate_evidence_summary == summary
    assert RunnerListItem(runner_id="runner-1", running=False, gate_evidence_summary=summary).gate_evidence_summary == summary
    assert MergeStatusResponse(runner_id="runner-1", status="error", gate_evidence_summary=summary).gate_evidence_summary == summary

    detail = _build_gate_failure_detail("blocked", summary)
    assert detail["message"] == "blocked"
    assert detail["detail"] == "blocked"
    assert detail["gate_evidence_summary"] == summary
