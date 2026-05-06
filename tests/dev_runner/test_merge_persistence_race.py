"""Late-writer ordering and display integration tests for merge lifecycle.

Axis map:
- late-writer ordering: stale gate writer after approval writer is rejected.
- display: approval_required outranks stale branch metadata in read model/display.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import sys


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


class AsyncFakeRedis:
    def __init__(self, store):
        self.store = store

    async def get(self, key):
        return self.store.get(key)


def _run_git(cwd, *args):
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_approval_required_survives_late_stale_gate_writer():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, ERROR, RetryAction

    rid = "race-approval-001"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis()
    persistence = MergePersistence(redis, rid)

    first = persistence.transition(
        APPROVAL_REQUIRED,
        reason="service_lock",
        message="MERGE_PRECHECK_FAILED[service_lock]: blocked",
        action=RetryAction.INLINE_MERGE,
    )
    late = persistence.transition(
        ERROR,
        reason="stale_merge_blocked",
        message="stale branch",
        action=RetryAction.INLINE_MERGE,
    )

    assert first.allowed is True
    assert late.allowed is False
    assert redis.get(f"{prefix}:merge_status") == APPROVAL_REQUIRED
    assert redis.get(f"{prefix}:merge_reason") == "service_lock"
    assert redis.get(f"{prefix}:merge_message") == "MERGE_PRECHECK_FAILED[service_lock]: blocked"


def test_approval_required_display_survives_stale_branch_metadata(tmp_path):
    from app.modules.dev_runner.services.runner_display_state import build_display_state
    from app.modules.dev_runner.services.runner_read_model import build_runner_read_model

    _run_git(tmp_path, "init")
    _run_git(tmp_path, "config", "user.email", "test@example.com")
    _run_git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "file.txt").write_text("initial\n", encoding="utf-8")
    _run_git(tmp_path, "add", "file.txt")
    _run_git(tmp_path, "commit", "-m", "initial")
    _run_git(tmp_path, "checkout", "-b", "impl/test")

    model = build_runner_read_model(
        runner_id="display-approval-001",
        running=False,
        merge_status="approval_required",
        exit_reason="completed",
        branch="impl/test",
        worktree_path=str(tmp_path),
        redis_branch_exists=False,
        redis_worktree_exists=True,
        repo_cwd=str(tmp_path),
    )
    display = build_display_state(model)

    assert model.branch_exists is True
    assert display.state == "approval_required"
    assert display.severity == "approval"
    assert display.hide_stale_branch_badge is True
    assert display.secondary is None


async def test_approval_required_persistence_flows_to_merge_status_payload():
    from _dr_merge_persistence import MergePersistence
    from _dr_merge_state import APPROVAL_REQUIRED, ERROR, RetryAction
    from app.modules.dev_runner.services.merge_service import MergeService

    rid = "payload-approval-001"
    prefix = f"plan-runner:runners:{rid}"
    redis = FakeRedis()
    persistence = MergePersistence(redis, rid)

    persistence.transition(
        APPROVAL_REQUIRED,
        reason="service_lock",
        message="MERGE_PRECHECK_FAILED[service_lock]: blocked",
        action=RetryAction.INLINE_MERGE,
    )
    rejected = persistence.transition(
        ERROR,
        reason="stale_merge_blocked",
        message="stale branch",
        action=RetryAction.INLINE_MERGE,
    )
    persistence.persist_result_metadata(
        {"success": False, "reason": "stale_merge_blocked", "message": "stale branch"}
    )

    service = MergeService(
        AsyncFakeRedis(redis.store),
        runner_key_fn=lambda runner_id, field: f"plan-runner:runners:{runner_id}:{field}",
        send_command_fn=lambda command: command,
    )
    payload = await service.get_merge_status(rid)

    assert rejected.allowed is False
    assert payload == {
        "runner_id": rid,
        "status": APPROVAL_REQUIRED,
        "test_passed": None,
        "fix_attempts": 0,
        "message": "MERGE_PRECHECK_FAILED[service_lock]: blocked",
        "reason": "service_lock",
        "quarantine_diff_path": None,
    }
