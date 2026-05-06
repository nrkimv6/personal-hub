"""Merge lock timeout contract regression tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_PLAN_RUNNER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))


def _import_dr_merge():
    import importlib

    return importlib.import_module("_dr_merge")


def test_inline_merge_uses_configured_lock_timeout(monkeypatch):
    dr_merge = _import_dr_merge()
    redis_client = MagicMock()
    captured = {}

    def fake_acquire(_redis, _runner_id, **kwargs):
        captured.update(kwargs)
        return False

    monkeypatch.delenv("MERGE_TEST_LOCK_TIMEOUT", raising=False)

    with patch("merge_queue.acquire_merge_turn", side_effect=fake_acquire), \
         patch("merge_queue.release_merge_turn") as release:
        result = dr_merge._execute_merge_with_lock("runner-timeout-default", redis_client)

    assert captured["timeout"] == 86400
    assert result["success"] is False
    assert "timeout=86400s" in result["message"]
    release.assert_not_called()


def test_inline_merge_env_timeout_overrides_default(monkeypatch):
    dr_merge = _import_dr_merge()
    redis_client = MagicMock()
    captured = {}

    def fake_acquire(_redis, _runner_id, **kwargs):
        captured.update(kwargs)
        return False

    monkeypatch.setenv("MERGE_TEST_LOCK_TIMEOUT", "77")

    with patch("merge_queue.acquire_merge_turn", side_effect=fake_acquire), \
         patch("merge_queue.release_merge_turn") as release:
        result = dr_merge._execute_merge_with_lock("runner-timeout-env", redis_client)

    assert captured["timeout"] == 77
    assert result["success"] is False
    assert "timeout=77s" in result["message"]
    release.assert_not_called()


def test_redis_unavailable_does_not_continue_lockless():
    dr_merge = _import_dr_merge()
    redis_client = MagicMock()

    with patch("merge_queue.acquire_merge_turn", side_effect=RuntimeError("redis unavailable")), \
         patch("merge_queue.release_merge_turn") as release, \
         patch.object(dr_merge.subprocess, "run") as subprocess_run:
        result = dr_merge._execute_merge_with_lock("runner-redis-down", redis_client)

    assert result["success"] is False
    assert result["merge_status"] == "error"
    assert "redis unavailable" in result["message"]
    subprocess_run.assert_not_called()
    release.assert_not_called()
