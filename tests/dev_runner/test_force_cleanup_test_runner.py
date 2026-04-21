import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.dev_runner._path_helpers import bootstrap_plan_runner_modules

try:
    import fakeredis

    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis 미설치")


def _import_process_utils():
    bootstrap_plan_runner_modules()
    return sys.modules["_dr_process_utils"]


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_force_cleanup_test_runner_worktree_when_test_source_present():
    mod = _import_process_utils()
    redis_client = _make_redis()
    redis_client.set("plan-runner:runners:t-clean-1234:test_source", "cleanup")
    redis_client.set("plan-runner:runners:t-clean-1234:worktree_path", "D:/repo/.worktrees/t-clean-1234")
    redis_client.set("plan-runner:runners:t-clean-1234:branch", "runner/t-clean-1234")

    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(mod.subprocess, "run", side_effect=_fake_run):
        result = mod._force_cleanup_test_runner_worktree("t-clean-1234", redis_client)

    assert result is True
    assert calls[0][:4] == ["git", "worktree", "remove", "--force"]
    assert calls[1] == ["git", "branch", "-D", "runner/t-clean-1234"]


def test_force_cleanup_test_runner_worktree_skips_without_test_source():
    mod = _import_process_utils()
    redis_client = _make_redis()

    with patch.object(mod.subprocess, "run") as mocked:
        result = mod._force_cleanup_test_runner_worktree("t-clean-5678", redis_client)

    assert result is False
    mocked.assert_not_called()


def test_force_cleanup_test_runner_worktree_tolerates_missing_worktree():
    mod = _import_process_utils()
    redis_client = _make_redis()
    redis_client.set("plan-runner:runners:t-clean-missing:test_source", "cleanup")
    redis_client.set("plan-runner:runners:t-clean-missing:branch", "runner/t-clean-missing")

    responses = [
        subprocess.CompletedProcess(
            ["git", "worktree", "remove", "--force", "D:/repo/.worktrees/t-clean-missing"],
            128,
            "",
            "fatal: 'D:/repo/.worktrees/t-clean-missing' is not a working tree",
        ),
        subprocess.CompletedProcess(
            ["git", "branch", "-D", "runner/t-clean-missing"],
            1,
            "",
            "error: branch 'runner/t-clean-missing' not found.",
        ),
    ]

    with patch.object(mod.subprocess, "run", side_effect=responses):
        result = mod._force_cleanup_test_runner_worktree("t-clean-missing", redis_client)

    assert result is True


def test_force_cleanup_test_runner_worktree_ignores_lock_and_ahead_metadata():
    mod = _import_process_utils()
    redis_client = _make_redis()
    redis_client.set("plan-runner:runners:t-clean-locked:test_source", "cleanup")
    redis_client.set("plan-runner:runners:t-clean-locked:worktree_path", "D:/repo/.worktrees/t-clean-locked")
    redis_client.set("plan-runner:runners:t-clean-locked:branch", "runner/t-clean-locked")
    redis_client.set("plan-runner:runners:t-clean-locked:locked", "1")
    redis_client.set("plan-runner:runners:t-clean-locked:ahead", "3")

    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(mod.subprocess, "run", side_effect=_fake_run):
        result = mod._force_cleanup_test_runner_worktree("t-clean-locked", redis_client)

    assert result is True
    assert calls[0][:4] == ["git", "worktree", "remove", "--force"]
    assert calls[1] == ["git", "branch", "-D", "runner/t-clean-locked"]


def test_cleanup_process_state_calls_force_cleanup_helper():
    mod = _import_process_utils()
    redis_client = _make_redis()
    runner_id = "t-clean-state"
    redis_client.set(f"plan-runner:runners:{runner_id}:status", "running")
    redis_client.set(f"plan-runner:runners:{runner_id}:test_source", "cleanup")
    redis_client.set(f"plan-runner:runners:{runner_id}:branch", f"runner/{runner_id}")
    redis_client.set(f"plan-runner:runners:{runner_id}:trigger", "user")

    with patch.object(mod, "_force_cleanup_test_runner_worktree", return_value=True) as mock_force:
        mod._cleanup_process_state(runner_id, redis_client, reason="test_force_cleanup")

    mock_force.assert_called_once_with(runner_id, redis_client)
