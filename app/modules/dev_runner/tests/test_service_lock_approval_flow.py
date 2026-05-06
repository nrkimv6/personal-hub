"""service_lock approval_required runtime flow tests (listener-side).

T3: exit code 5(approval_required) 보존 + approve_service_lock 1회 플래그 계약 검증.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _FakeRedis:
    def __init__(self, initial: dict | None = None):
        self.store = dict(initial or {})
        self.published: list[tuple[str, str]] = []
        self.lpush_items: list[tuple[str, str]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, **kwargs):
        self.store[key] = value
        return True

    def delete(self, key: str):
        self.store.pop(key, None)
        return True

    def expire(self, key: str, ttl: int):
        return True

    def persist(self, key: str):
        return True

    def publish(self, channel: str, message: str):
        self.published.append((channel, message))
        return 1

    def rpush(self, key: str, value: str):
        return True

    def lpush(self, key: str, value: str):
        self.lpush_items.append((key, value))
        return True


def _import_plan_runner_modules():
    repo_root = Path(__file__).resolve().parents[4]
    plan_runner_dir = repo_root / "scripts" / "plan_runner"
    if str(plan_runner_dir) not in sys.path:
        sys.path.insert(0, str(plan_runner_dir))
    import _dr_merge  # type: ignore
    import _dr_commands  # type: ignore
    import merge_queue  # type: ignore

    return _dr_merge, _dr_commands, merge_queue


def test_execute_merge_with_lock_exit_5_preserves_approval_required():
    """T3-R: post-merge exit code 5(service_lock) → approval_required로 보존, general resolver 미호출."""
    _dr_merge, _dr_commands, merge_queue = _import_plan_runner_modules()

    rid = "t-approval-001"
    prefix = f"plan-runner:runners:{rid}"
    fake = _FakeRedis(
        {
            f"{prefix}:branch": "impl/test",
            f"{prefix}:plan_file": "docs/plan/test.md",
            f"{prefix}:merge_message": "MERGE_PRECHECK_FAILED[service_lock]: blocked",
            f"{prefix}:merge_reason": "service_lock",
        }
    )

    with patch.object(merge_queue, "acquire_merge_turn", return_value=True), \
         patch.object(merge_queue, "release_merge_turn", return_value=None), \
         patch.object(merge_queue, "_get_repo_id", return_value="repo"), \
         patch.object(_dr_merge.subprocess, "run", return_value=SimpleNamespace(returncode=5)), \
         patch.object(_dr_merge, "_handle_general_error", side_effect=AssertionError("general resolver should not be used")):
        result = _dr_merge._execute_merge_with_lock(rid, fake, action_name="inline-merge")  # noqa: SLF001

    assert result["success"] is False
    assert result["merge_status"] == "approval_required"
    assert result.get("reason") == "service_lock"
    assert "MERGE_PRECHECK_FAILED[service_lock]" in result.get("message", "")


def test_retry_merge_sets_and_clears_service_lock_approved_flag():
    """T3-R: retry-merge approve_service_lock=true → Redis 1회 플래그 세팅 후 시도 종료 시 제거."""
    _dr_merge, _dr_commands, merge_queue = _import_plan_runner_modules()

    rid = "t-approval-002"
    prefix = f"plan-runner:runners:{rid}"
    flag_key = f"{prefix}:service_lock_approved"
    fake = _FakeRedis({f"{prefix}:worktree_path": "D:/tmp/wt"})

    def _stub_execute_merge_with_lock(_rid, redis_client, action_name="retry-merge", _test_fix_attempt=0):
        assert redis_client.get(flag_key) == "true"
        return {"success": False, "merge_status": "approval_required", "message": "blocked", "reason": "service_lock"}

    with patch("plan_runner.core.stages.pre_merge_gate", return_value=(True, "ok")), \
         patch("plan_runner.core.stages.auto_commit_stage", return_value=False), \
         patch.object(_dr_commands, "_execute_merge_with_lock", side_effect=_stub_execute_merge_with_lock), \
         patch.object(_dr_commands, "_cleanup_process_state", return_value=None):
        _dr_commands._do_retry_merge(  # noqa: SLF001
            rid,
            fake,
            "cmd01",
            command={"approve_service_lock": True},
        )

    assert fake.get(flag_key) is None
