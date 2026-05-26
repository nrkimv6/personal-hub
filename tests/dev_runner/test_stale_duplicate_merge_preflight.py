from __future__ import annotations

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
