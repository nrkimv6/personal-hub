import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from app.shared.process.worktree_residue_monitor import WorktreeResidueMonitor


def test_record_scan_sets_zero_baseline_and_tracks_nonzero(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    project_root = tmp_path / "monitor-page"
    project_root.mkdir()

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        zero_status = WorktreeResidueMonitor.record_scan([], source="test", repo_root=project_root)
        nonzero_status = WorktreeResidueMonitor.record_scan(
            ["runner/t-demo-001", "plan/test_demo"],
            source="test",
            repo_root=project_root,
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
    assert nonzero_status["latest_legacy_test_branch_count"] == 1
    assert nonzero_status["latest_legacy_test_branches"] == ["plan/test_demo"]

    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    latest_event = json.loads(lines[-1])
    assert latest_event["type"] == "scan"
    assert latest_event["scope"] == "operational"
    assert latest_event["repo_root"] == str(project_root.resolve())
    assert latest_event["test_branch_count"] == 2
    assert latest_event["legacy_test_branch_count"] == 1
    assert latest_event["legacy_test_branches"] == ["plan/test_demo"]


def test_record_scan_ignores_temp_repo_without_status_mutation(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    project_root = tmp_path / "monitor-page"
    temp_repo = tmp_path / "pytest-of-Narang" / "repo"
    project_root.mkdir()
    temp_repo.mkdir(parents=True)

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        baseline = WorktreeResidueMonitor.record_scan([], source="test", repo_root=project_root)
        ignored = WorktreeResidueMonitor.record_scan(
            ["runner/t-temp-001"],
            source="test",
            repo_root=temp_repo,
        )

    assert baseline["latest_test_branch_count"] == 0
    assert ignored["latest_test_branch_count"] == 0
    assert ignored["nonzero_seen_since_baseline"] is False

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    ignored_event = events[-1]
    assert ignored_event["type"] == "scan_ignored"
    assert ignored_event["scope"] == "ignored"
    assert ignored_event["ignored_reason"] == "outside_project_root"
    assert ignored_event["repo_root"] == str(temp_repo.resolve())
    assert ignored_event["test_branches"] == ["runner/t-temp-001"]


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
    project_root = tmp_path / "monitor-page"
    project_root.mkdir()
    worktree_path = project_root / ".worktrees" / "t-clean-001"

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        status = WorktreeResidueMonitor.record_cleanup(
            event_type="force_cleanup",
            branches=["runner/t-clean-001"],
            source="test",
            runner_id="t-clean-001",
            test_source="cleanup_test",
            worktree_path=str(worktree_path),
            repo_root=project_root,
        )

    assert status["force_cleanup_event_count"] == 1
    assert status["force_cleanup_branch_count"] == 1
    assert status["last_force_cleanup"]["runner_id"] == "t-clean-001"
    assert status["last_force_cleanup"]["scope"] == "operational"
    assert status["last_force_cleanup"]["repo_root"] == str(project_root.resolve())

    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["type"] == "force_cleanup"
    assert event["scope"] == "operational"
    assert event["branches"] == ["runner/t-clean-001"]


def test_record_cleanup_ignores_temp_repo_without_incrementing_counter(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    project_root = tmp_path / "monitor-page"
    temp_repo = tmp_path / "pytest-of-Narang" / "repo"
    project_root.mkdir()
    temp_repo.mkdir(parents=True)

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        status = WorktreeResidueMonitor.record_cleanup(
            event_type="force_cleanup",
            branches=["runner/t-temp-001"],
            source="test",
            runner_id="t-temp-001",
            test_source="cleanup_test",
            worktree_path=str(temp_repo / ".worktrees" / "t-temp-001"),
            repo_root=project_root,
        )

    assert status["force_cleanup_event_count"] == 0
    assert status["force_cleanup_branch_count"] == 0
    assert status["last_force_cleanup"] is None

    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["type"] == "force_cleanup_ignored"
    assert event["scope"] == "ignored"
    assert event["ignored_reason"] == "outside_project_root"
    assert event["repo_root"] == str(project_root.resolve())
    assert event["worktree_path"] == str((temp_repo / ".worktrees" / "t-temp-001").resolve())


def test_real_tmp_git_repo_scan_does_not_pollute_operational_status(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    project_root = tmp_path / "monitor-page"
    temp_repo = tmp_path / "pytest-of-Narang" / "repo"
    project_root.mkdir()
    temp_repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init"],
        cwd=temp_repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        WorktreeResidueMonitor.record_scan([], source="test", repo_root=project_root)
        WorktreeResidueMonitor.record_scan(
            ["runner/t-temp-002"],
            source="test",
            repo_root=temp_repo,
        )
        operational_status = WorktreeResidueMonitor.record_scan(
            ["runner/t-operational-001"],
            source="test",
            repo_root=project_root,
        )

    assert operational_status["latest_test_branch_count"] == 1
    assert operational_status["latest_test_branches"] == ["runner/t-operational-001"]
    assert operational_status["nonzero_seen_since_baseline"] is True

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["type"] for event in events]
    assert "scan_ignored" in event_types
    assert "baseline_regressed" in event_types


def test_rebase_status_to_operational_scope_records_decision_event(tmp_path):
    events_path = tmp_path / "worktree_residue_events.jsonl"
    status_path = tmp_path / "worktree_residue_status.json"
    project_root = tmp_path / "monitor-page"
    project_root.mkdir()

    with patch.object(WorktreeResidueMonitor, "EVENTS_PATH", events_path), \
         patch.object(WorktreeResidueMonitor, "STATUS_PATH", status_path), \
         patch.object(WorktreeResidueMonitor, "PROJECT_ROOT", project_root):
        status = WorktreeResidueMonitor.rebase_status_to_operational_scope(
            source="test",
            latest_branches=[],
            reason="exclude historical pytest temp repo cleanup metadata",
            repo_root=project_root,
        )

    assert status["latest_test_branch_count"] == 0
    assert status["nonzero_seen_since_baseline"] is False
    assert status["baseline_zero_confirmed_at"] is not None

    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["type"] == "monitor_scope_rebased"
    assert event["scope"] == "operational"
    assert event["repo_root"] == str(project_root.resolve())
    assert event["reason"] == "exclude historical pytest temp repo cleanup metadata"
