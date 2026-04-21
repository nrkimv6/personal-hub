import json
from pathlib import Path
from unittest.mock import patch

from app.shared.process.worktree_residue_monitor import WorktreeResidueMonitor


def test_record_scan_sets_zero_baseline_and_tracks_nonzero(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path):
        zero_status = WorktreeResidueMonitor.record_scan([], source="test")
        nonzero_status = WorktreeResidueMonitor.record_scan(
            ["runner/t-demo-001", "plan/test_demo"],
            source="test",
        )

    assert zero_status["baseline_zero_confirmed_at"] is not None
    assert nonzero_status["latest_test_branch_count"] == 2
    assert nonzero_status["nonzero_seen_since_baseline"] is True
    assert nonzero_status["max_test_branch_count_since_baseline"] == 2
    assert nonzero_status["last_nonzero_branches"] == [
        "plan/test_demo",
        "runner/t-demo-001",
    ]

    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    latest_event = json.loads(lines[-1])
    assert latest_event["type"] == "scan"
    assert latest_event["test_branch_count"] == 2


def test_record_cleanup_updates_status_and_appends_jsonl(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path):
        status = WorktreeResidueMonitor.record_cleanup(
            event_type="force_cleanup",
            branches=["runner/t-clean-001"],
            source="test",
            runner_id="t-clean-001",
            test_source="cleanup_test",
            worktree_path="D:/repo/.worktrees/t-clean-001",
        )

    assert status["force_cleanup_event_count"] == 1
    assert status["force_cleanup_branch_count"] == 1
    assert status["last_force_cleanup"]["runner_id"] == "t-clean-001"

    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["type"] == "force_cleanup"
    assert event["branches"] == ["runner/t-clean-001"]
