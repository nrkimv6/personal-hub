"""Merge persistence 6-axis tests.

Axis map:
- preserver: queued/error writes preserve an existing approval_required state.
- overwrite-block: stale gate error is rejected after terminal approval state.
- override: approved retry may intentionally leave approval_required.
- late-writer ordering: tests call terminal writer before later stale writer.
"""

from pathlib import Path
import sys
import json


ROOT = Path(__file__).resolve().parents[2]
PLAN_RUNNER_DIR = ROOT / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))


class FakeRedis:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, **kwargs):
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return True

    def lpush(self, key, value):
        self.store.setdefault(key, [])
        self.store[key].insert(0, value)
        return True

    def expire(self, key, ttl):
        return True


def test_transition_queued_preserves_approval_required():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, QUEUED, RetryAction

    rid = "runner-a"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis({f"{prefix}:merge_status": APPROVAL_REQUIRED})

    result = MergePersistence(redis, rid).transition(QUEUED, action=RetryAction.INLINE_MERGE)

    assert result.allowed is False
    assert redis.get(f"{prefix}:merge_status") == APPROVAL_REQUIRED


def test_transition_error_preserves_approval_required_but_allows_merging_source():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, ERROR, MERGING, RetryAction

    rid = "runner-b"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis({f"{prefix}:merge_status": APPROVAL_REQUIRED})

    blocked = MergePersistence(redis, rid).transition(ERROR, reason="stale_merge_blocked", action=RetryAction.INLINE_MERGE)
    assert blocked.allowed is False
    assert redis.get(f"{prefix}:merge_status") == APPROVAL_REQUIRED

    redis = FakeRedis({f"{prefix}:merge_status": MERGING})
    allowed = MergePersistence(redis, rid).transition(ERROR, reason="stale_merge_blocked", action=RetryAction.INLINE_MERGE)
    assert allowed.allowed is True
    assert redis.get(f"{prefix}:merge_status") == ERROR
    assert redis.get(f"{prefix}:merge_reason") == "stale_merge_blocked"


def test_approved_retry_can_leave_approval_required():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, MERGING, RetryAction

    rid = "runner-c"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis({f"{prefix}:merge_status": APPROVAL_REQUIRED})

    result = MergePersistence(redis, rid).transition(MERGING, action=RetryAction.APPROVED_RETRY)

    assert result.allowed is True
    assert redis.get(f"{prefix}:merge_status") == MERGING


def test_result_metadata_preserves_terminal_approval_after_rejected_late_writer():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, ERROR, RetryAction

    rid = "runner-d"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis(
        {
            f"{prefix}:merge_status": APPROVAL_REQUIRED,
            f"{prefix}:merge_reason": "service_lock",
            f"{prefix}:merge_message": "MERGE_PRECHECK_FAILED[service_lock]: blocked",
        }
    )
    persistence = MergePersistence(redis, rid)

    rejected = persistence.transition(
        ERROR,
        reason="stale_merge_blocked",
        message="stale branch",
        action=RetryAction.INLINE_MERGE,
    )
    persistence.persist_result_metadata(
        {"success": False, "reason": "stale_merge_blocked", "message": "stale branch"}
    )
    persistence.push_result_history(
        branch="impl/test",
        plan_file="docs/plan/test.md",
        result={"success": False, "reason": "stale_merge_blocked", "message": "stale branch"},
    )

    assert rejected.allowed is False
    assert redis.get(f"{prefix}:merge_status") == APPROVAL_REQUIRED
    assert redis.get(f"{prefix}:merge_reason") == "service_lock"
    assert redis.get(f"{prefix}:merge_message") == "MERGE_PRECHECK_FAILED[service_lock]: blocked"
    history = json.loads(redis.get("plan-runner:merge-results")[0])
    assert history["status"] == APPROVAL_REQUIRED


def test_extract_service_lock_details_parses_changed_and_running_R():
    from _dr_merge_persistence import MergePersistence

    msg = (
        "MERGE_PRECHECK_FAILED[service_lock]: Running 서비스와 겹치는 변경이 감지되어 승인 대기 상태로 전환합니다.\n"
        "- changed: scripts/services/service_run.py\n"
        "- running: MonitorPage-Admin, MonitorPage-Public"
    )
    details = MergePersistence._extract_service_lock_details(msg)
    assert details["service_lock_changed"] == ["scripts/services/service_run.py"]
    assert details["service_lock_running"] == ["MonitorPage-Admin", "MonitorPage-Public"]


def test_extract_service_lock_details_empty_message_R():
    from _dr_merge_persistence import MergePersistence

    assert MergePersistence._extract_service_lock_details("") == {}
    assert MergePersistence._extract_service_lock_details(None) == {}


def test_build_gate_evidence_summary_includes_service_lock_details_R():
    from _dr_merge_persistence import MergePersistence

    msg = (
        "MERGE_PRECHECK_FAILED[service_lock]: blocked\n"
        "- changed: scripts/services/service_run.py\n"
        "- running: MonitorPage-Admin"
    )
    result = {
        "success": False,
        "merge_status": "approval_required",
        "reason": "service_lock",
        "message": msg,
    }
    summary = MergePersistence.build_gate_evidence_summary(result)
    assert summary is not None
    assert summary["service_lock_changed"] == ["scripts/services/service_run.py"]
    assert summary["service_lock_running"] == ["MonitorPage-Admin"]
    assert summary["reason"] == "service_lock"


def test_build_gate_evidence_summary_no_service_lock_details_when_reason_differs_R():
    from _dr_merge_persistence import MergePersistence

    result = {
        "success": False,
        "merge_status": "error",
        "reason": "test_failed",
        "message": "- changed: something\n- running: nope",
    }
    summary = MergePersistence.build_gate_evidence_summary(result)
    assert summary is not None
    assert "service_lock_changed" not in summary
    assert "service_lock_running" not in summary
