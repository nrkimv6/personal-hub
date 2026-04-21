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
    assert zero_status["review_due_at"] is not None
    assert zero_status["remove_monitor_candidate_at"] == zero_status["review_due_at"]
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


def test_record_scan_emits_review_due_event_once(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    status_path.write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": "2026-04-21T01:11:39+00:00",
                "updated_at": "2026-04-21T01:11:39+00:00",
                "baseline_zero_confirmed_at": "2026-04-21T01:11:39+00:00",
                "latest_scan_at": "2026-04-21T01:11:39+00:00",
                "latest_source": "test",
                "latest_test_branch_count": 0,
                "latest_test_branches": [],
                "max_test_branch_count_since_baseline": 0,
                "nonzero_seen_since_baseline": False,
                "monitoring_reason": "Watch for recurring test worktree residue after zero baseline.",
                "review_due_at": "2026-04-28T01:11:39+00:00",
                "remove_monitor_candidate_at": "2026-04-28T01:11:39+00:00",
                "review_due_logged_at": None,
                "last_nonzero_at": None,
                "last_nonzero_branches": [],
                "force_cleanup_event_count": 0,
                "force_cleanup_branch_count": 0,
                "orphan_cleanup_event_count": 0,
                "orphan_cleanup_branch_count": 0,
                "last_force_cleanup": None,
                "last_orphan_cleanup": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(
             WorktreeResidueMonitor,
             "_utcnow",
             side_effect=["2026-04-28T01:11:40+00:00", "2026-04-28T01:11:41+00:00"],
         ):
        due_status = WorktreeResidueMonitor.record_scan([], source="test")
        after_due_status = WorktreeResidueMonitor.record_scan([], source="test")

    assert due_status["review_due_logged_at"] == "2026-04-28T01:11:40+00:00"
    assert after_due_status["review_due_logged_at"] == "2026-04-28T01:11:40+00:00"

    event_types = [
        json.loads(line)["type"]
        for line in events_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert event_types.count("monitor_review_due") == 1


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
