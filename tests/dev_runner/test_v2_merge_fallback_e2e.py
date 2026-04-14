"""T4: v2 merge fallback verification.

Tests the fallback detection when a runner has merged its worktree but crashed before completing the 'done' stage.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts path setup
import sys
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_PLAN_RUNNER_DIR = _SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

def _make_mock_process(exit_code=0, lines=None):
    proc = MagicMock()
    proc.returncode = exit_code
    proc.stdout = MagicMock()
    proc.stdout.readline.side_effect = (lines or []) + [""]
    proc.poll.return_value = exit_code
    return proc

def test_v2_merge_fallback_e2e_stream_output_R(monkeypatch, tmp_path):
    """T4 R: subprocess exit(15) + detect success -> _handle_post_merge_done called"""
    from _dr_plan_runner import _stream_output
    import _dr_process_utils as _putils

    monkeypatch.setattr("plan_worktree_helpers.is_plan_in_progress", lambda *a, **kw: False, raising=False)
    monkeypatch.setattr("plan_worktree_helpers.has_unmerged_commits", lambda *a, **kw: False, raising=False)

    runner_id = "e2e-test-runner-t4"
    plan_file = str(tmp_path / "test_plan.md")
    Path(plan_file).write_text("> Status: merging\n- [x] task1\n", encoding="utf-8")

    proc = _make_mock_process(exit_code=15)
    log_file = tmp_path / "runner.log"
    log_file.write_text("", encoding="utf-8")

    redis_mock = MagicMock()
    redis_mock.get.return_value = None  # merge_requested=None (v2 path)

    called = []

    with patch("_dr_stream_cleanup.detect_merged_but_not_done",
               return_value={"plan_file": plan_file, "branch": "plan/e2e-test"}) as mock_detect, \
         patch("_dr_stream_cleanup._handle_post_merge_done", side_effect=lambda *a, **kw: called.append(a[0])) as mock_done, \
         patch("_dr_stream_cleanup._cleanup_process_state"), \
         patch("_dr_merge._pub_and_log"), \
         patch.dict(_putils.get_stream_threads() if hasattr(_putils, "get_stream_threads") else {}, {}), \
         open(str(log_file), "a", encoding="utf-8") as lh:
        _stream_output(proc, lh, redis_mock, runner_id)

    assert mock_detect.called, "detect_merged_but_not_done should be called"
    assert mock_done.called, "_handle_post_merge_done should be called"
    assert len(called) > 0
    assert called[0] == plan_file

def test_v2_merge_fallback_e2e_stream_output_no_merge_B(monkeypatch, tmp_path):
    """T4 B: detect returns None -> _handle_post_merge_done not called, cleanup runs"""
    from _dr_plan_runner import _stream_output

    monkeypatch.setattr("plan_worktree_helpers.is_plan_in_progress", lambda *a, **kw: False, raising=False)
    monkeypatch.setattr("plan_worktree_helpers.has_unmerged_commits", lambda *a, **kw: False, raising=False)

    runner_id = "e2e-test-runner-t4-skip"
    proc = _make_mock_process(exit_code=0, lines=["[info] test complete\n"])
    log_file = tmp_path / "runner.log"
    log_file.write_text("", encoding="utf-8")

    redis_mock = MagicMock()
    redis_mock.get.return_value = None

    with patch("_dr_stream_cleanup.detect_merged_but_not_done", return_value=None), \
         patch("_dr_stream_cleanup._handle_post_merge_done") as mock_done, \
         patch("_dr_stream_cleanup._cleanup_process_state") as mock_cleanup, \
         patch("_dr_merge._pub_and_log"), \
         open(str(log_file), "a", encoding="utf-8") as lh:
        _stream_output(proc, lh, redis_mock, runner_id)

    mock_done.assert_not_called()
    assert mock_cleanup.called, "_cleanup_process_state should be called"


