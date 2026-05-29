from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, object] = {}
        self.set_calls: list[tuple[str, object]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, **kwargs):
        self.set_calls.append((key, value))
        self.store[key] = value
        return True

    def delete(self, key: str):
        self.store.pop(key, None)
        return 1


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def _import_dr_merge():
    repo_root = Path(__file__).resolve().parents[2]
    plan_runner_dir = repo_root / "scripts" / "plan_runner"
    if str(plan_runner_dir) not in sys.path:
        sys.path.insert(0, str(plan_runner_dir))
    import _dr_merge  # type: ignore

    return _dr_merge


def test_duplicate_patch_merge_preflight_hard_blocks_even_when_stale_risk_passes():
    mod = _import_dr_merge()
    fake = _FakeRedis()
    evidence = {
        "blockers": ["duplicate_patch_blocked"],
        "warnings": [],
        "duplicates": [{"commit": "abc1234", "subject": "old patch", "patch_id": "pid", "paths": ["x.py"]}],
        "path_overlap_ratio": 1.0,
    }

    with patch("plan_worktree_helpers.get_branch_divergence", return_value=(1, 1)), \
         patch("plan_worktree_helpers.classify_merge_risk", return_value="PASS"), \
         patch.object(mod, "_candidate_tip_evidence", return_value=evidence):
        result, snapshot = mod._check_stale_merge_gate(  # noqa: SLF001
            "runner-duplicate-preflight",
            fake,
            "impl/stale",
            lambda _msg: None,
        )

    assert snapshot is None
    assert result["reason"] == "duplicate_patch_blocked"
    assert result["candidate_tip"]["duplicates"][0]["paths"] == ["x.py"]


def test_stale_ancestry_merge_preflight_hard_blocks_even_when_behind_warn_would_pass():
    mod = _import_dr_merge()
    fake = _FakeRedis()
    evidence = {
        "blockers": ["stale_ancestry_blocked"],
        "warnings": [],
        "duplicates": [],
        "path_overlap_ratio": 0.0,
    }

    with patch("plan_worktree_helpers.get_branch_divergence", return_value=(1, 1)), \
         patch("plan_worktree_helpers.classify_merge_risk", return_value="PASS"), \
         patch.object(mod, "_candidate_tip_evidence", return_value=evidence):
        result, snapshot = mod._check_stale_merge_gate(  # noqa: SLF001
            "runner-stale-preflight",
            fake,
            "impl/stale",
            lambda _msg: None,
        )

    assert snapshot is None
    assert result["reason"] == "stale_ancestry_blocked"
    assert result["candidate_tip"]["blockers"] == ["stale_ancestry_blocked"]


def test_candidate_tip_repairable_merge_is_not_hard_blocker():
    mod = _import_dr_merge()
    fake = _FakeRedis()
    evidence = {
        "blockers": [],
        "warnings": [],
        "duplicates": [],
        "path_overlap_ratio": 0.0,
        "repairable_merge_commits": [
            {
                "commit": "merge123",
                "base_parent": "base123",
                "candidate_parent": "candidate123",
                "repair": "linearize_to_candidate_parent",
            }
        ],
    }

    with patch("plan_worktree_helpers.get_branch_divergence", return_value=(0, 1)), \
         patch("plan_worktree_helpers.classify_merge_risk", return_value="PASS"), \
         patch.object(mod, "_candidate_tip_evidence", return_value=evidence), \
         patch.object(mod, "_write_pre_merge_snapshot", return_value="snapshot.json"):
        result, snapshot = mod._check_stale_merge_gate(  # noqa: SLF001
            "runner-repairable-preflight",
            fake,
            "impl/repairable",
            lambda _msg: None,
        )

    assert result is None
    assert snapshot == "snapshot.json"
    persisted = fake.store["plan-runner:runners:runner-repairable-preflight:candidate_tip_evidence"]
    assert "repairable_merge_commits" in persisted


def test_candidate_tip_evidence_marks_linearizable_merge_commit(tmp_path):
    mod = _import_dr_merge()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "feature")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    feature_tip = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-b", "accidental-merge", "main")
    _git(repo, "merge", "--no-ff", "feature", "-m", "merge feature")
    merge_tip = _git(repo, "rev-parse", "HEAD")

    evidence = mod._candidate_tip_evidence(repo, "main", "accidental-merge")  # noqa: SLF001

    assert evidence["blockers"] == []
    assert evidence["merge_commits"] == [merge_tip]
    assert evidence["repairable_merge_commits"] == [
        {
            "commit": merge_tip,
            "base_parent": _git(repo, "rev-parse", "main"),
            "candidate_parent": feature_tip,
            "repair": "linearize_to_candidate_parent",
        }
    ]


def test_merge_success_records_push_required_before_merged_handoff():
    mod = _import_dr_merge()
    fake = _FakeRedis()
    runner_id = "runner-push-required"
    messages: list[str] = []
    evidence = {
        "remote_ref": "origin/main",
        "available": True,
        "left": 1,
        "right": 0,
        "relation": "ahead-only",
        "closeout_status": "push_required",
    }

    with patch.object(mod, "_check_post_merge_residue", return_value={"success": True}), \
         patch.object(mod, "_post_merge_remote_alignment", return_value=evidence), \
         patch.object(mod, "_handle_post_merge_done") as done_mock:
        result = mod._handle_merge_success(  # noqa: SLF001
            runner_id,
            fake,
            "plan.md",
            messages.append,
        )

    assert result["success"] is False
    assert result["merge_status"] == "push_required"
    assert result["reason"] == "push_required"
    assert result["push_required"] is True
    assert result["remote_alignment"] == evidence
    assert fake.store[f"plan-runner:runners:{runner_id}:merge_status"] == "push_required"
    assert fake.store[f"plan-runner:runners:{runner_id}:merge_reason"] == "push_required"
    assert "push_required" in fake.store[f"plan-runner:runners:{runner_id}:remote_alignment_evidence"]
    assert any("push_required" in message for message in messages)
    done_mock.assert_not_called()
