"""Worktree leak prevention tests

Phase 3 verification:
- stale intermediate worktree cleanup logic
- conflict state worktree preservation
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing


# ========== Module Load ==========

_listener_mod = None


def _load_listener_mod():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


# ========== TC ==========

class TestCleanupStateIntermediateStatus:
    """Test _cleanup_process_state for intermediate merge statuses"""

    def test_cleanup_state_merging_cleans_worktree(self):
        """Right: merge_status='merging' -> call remove()"""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "t-wtleak-merging"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "merging")

        listener_mod = _load_listener_mod()

        with patch.object(listener_mod.WorktreeManager, "remove", return_value=True) as mock_remove:
            listener_mod._running_processes.clear()
            listener_mod._running_log_files.clear()
            listener_mod._stream_threads.clear()
            listener_mod._cleanup_process_state(runner_id, fake_redis, reason="test")

        mock_remove.assert_called_once()

    def test_cleanup_state_testing_cleans_worktree(self):
        """Right: merge_status='testing' -> call remove()"""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "t-wtleak-testing"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "testing")

        listener_mod = _load_listener_mod()

        with patch.object(listener_mod.WorktreeManager, "remove", return_value=True) as mock_remove:
            listener_mod._running_processes.clear()
            listener_mod._running_log_files.clear()
            listener_mod._stream_threads.clear()
            listener_mod._cleanup_process_state(runner_id, fake_redis, reason="test")

        mock_remove.assert_called_once()

    def test_cleanup_state_pending_merge_preserves_worktree(self):
        """Boundary: merge_status='pending_merge' -> no remove()"""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "t-wtleak-pndmrg"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "pending_merge")

        listener_mod = _load_listener_mod()

        with patch.object(listener_mod.WorktreeManager, "remove", return_value=True) as mock_remove:
            listener_mod._running_processes.clear()
            listener_mod._running_log_files.clear()
            listener_mod._stream_threads.clear()
            listener_mod._cleanup_process_state(runner_id, fake_redis, reason="test")

        mock_remove.assert_not_called()

    def test_cleanup_state_conflict_preserves_worktree(self):
        """Boundary: merge_status='conflict' -> no remove()"""
        fake_redis = fakeredis.FakeRedis(decode_responses=True)
        runner_id = "t-wtleak-cnflct"
        fake_redis.set(f"plan-runner:runners:{runner_id}:merge_status", "conflict")

        listener_mod = _load_listener_mod()

        with patch.object(listener_mod.WorktreeManager, "remove", return_value=True) as mock_remove:
            listener_mod._running_processes.clear()
            listener_mod._running_log_files.clear()
            listener_mod._stream_threads.clear()
            listener_mod._cleanup_process_state(runner_id, fake_redis, reason="test")

        mock_remove.assert_not_called()

