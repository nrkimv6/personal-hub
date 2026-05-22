from __future__ import annotations

import json
from unittest.mock import patch

import fakeredis

from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules


RUNNER_KEY_PREFIX = "plan-runner:runners"
COMMANDS_KEY = "plan-runner:commands"


def _redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_service_lock_approval_required_preserves_test_source_runner():
    bootstrap_plan_runner_modules()
    import _dr_merge
    import _dr_process_utils

    redis_client = _redis()
    runner_id = "t-service-lock"
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source", "pipeline-v2")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", f"runner/{runner_id}")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", f"D:/repo/.worktrees/{runner_id}")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_reason", "service_lock")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_message", "service lock blocked")

    with patch.object(_dr_merge, "_handle_general_error") as general_error:
        result = _dr_merge._handle_approval_required(
            runner_id=runner_id,
            redis_client=redis_client,
            plan_file="docs/plan/test.md",
            pub_fn=lambda msg: None,
            action_name="inline-merge",
        )

    assert result["merge_status"] == "approval_required"
    assert result["reason"] == "service_lock"
    general_error.assert_not_called()

    with patch.object(_dr_process_utils, "_force_cleanup_test_runner_worktree", return_value=True) as force_cleanup:
        _dr_process_utils._cleanup_process_state(runner_id, redis_client, reason="service_lock_preserve")

    force_cleanup.assert_not_called()
    assert redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path") == f"D:/repo/.worktrees/{runner_id}"


def test_restart_after_merge_requeues_test_source_and_test_repo_root():
    bootstrap_plan_runner_modules()
    import _dr_stream_cleanup

    redis_client = _redis()
    runner_id = "t-restart-context"
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/restart.md")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine", "codex")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine", "codex-mini")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_source", "pipeline-v2")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:test_repo_root", "D:/tmp/pipeline-v2-repo")
    redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge", "1")

    with patch.object(_dr_stream_cleanup, "_execute_merge_with_lock") as merge, \
         patch.object(_dr_stream_cleanup, "_cleanup_process_state"), \
         patch.object(_dr_stream_cleanup, "_cleanup_runner_ownership_snapshot"):
        merge.return_value = {"post_merge_done": {"status": "restart_scheduled"}}
        _dr_stream_cleanup._do_inline_merge(runner_id, redis_client)

    raw = redis_client.lpop(COMMANDS_KEY)
    assert raw is not None
    command = json.loads(raw)
    assert command["action"] == "run"
    assert command["plan_file"] == "docs/plan/restart.md"
    assert command["engine"] == "codex"
    assert command["fix_engine"] == "codex-mini"
    assert command["trigger"] == "user"
    assert command["test_source"] == "pipeline-v2"
    assert command["test_repo_root"] == "D:/tmp/pipeline-v2-repo"
    assert redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:restart_after_merge") is None
