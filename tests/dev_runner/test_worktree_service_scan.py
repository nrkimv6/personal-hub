"""scan_plan_files 단위 테스트"""

from pathlib import Path
from unittest.mock import patch

import app.modules.dev_runner.services.worktree_service as svc


def test_scan_plan_files_right_branch_mapping(tmp_path: Path):
    plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
    legacy_dir = tmp_path / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)

    (plans_dir / "plan-a.md").write_text("> branch: impl/a\n", encoding="utf-8")
    (legacy_dir / "plan-b.md").write_text("> branch: impl/b\n", encoding="utf-8")
    (legacy_dir / "plan-c.md").write_text("# no branch header\n", encoding="utf-8")

    branch_map, unresolved = svc.scan_plan_files(repo_root=tmp_path)

    assert branch_map["impl/a"][0].replace("\\", "/") == ".worktrees/plans/docs/plan/plan-a.md"
    assert branch_map["impl/b"][0].replace("\\", "/") == "docs/plan/plan-b.md"
    assert unresolved == [
        {
            "plan_file": str(Path("docs/plan/plan-c.md")),
            "reason": "missing > branch header",
            "plan_mtime": unresolved[0]["plan_mtime"],
        }
    ]


def test_scan_plan_files_boundary_prefers_plans_worktree_for_same_branch(tmp_path: Path):
    plans_dir = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
    legacy_dir = tmp_path / "docs" / "plan"
    plans_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)

    (plans_dir / "preferred.md").write_text("> branch: impl/same\n", encoding="utf-8")
    (legacy_dir / "fallback.md").write_text("> branch: impl/same\n", encoding="utf-8")

    branch_map, unresolved = svc.scan_plan_files(repo_root=tmp_path)

    assert unresolved == []
    assert branch_map["impl/same"][0].replace("\\", "/") == ".worktrees/plans/docs/plan/preferred.md"


def test_scan_plan_files_error_unreadable_file_skipped(tmp_path: Path):
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    good_file = plan_dir / "good.md"
    bad_file = plan_dir / "bad.md"
    good_file.write_text("> branch: impl/good\n", encoding="utf-8")
    bad_file.write_text("> branch: impl/bad\n", encoding="utf-8")

    original_open = open

    def fake_open(path, *args, **kwargs):
        if Path(path) == bad_file:
            raise OSError("boom")
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=fake_open):
        branch_map, unresolved = svc.scan_plan_files(repo_root=tmp_path)

    assert branch_map == {"impl/good": (str(Path("docs/plan/good.md")), branch_map["impl/good"][1])}
    assert unresolved == []


def test_scan_plan_files_correct_existence_missing_dirs(tmp_path: Path):
    branch_map, unresolved = svc.scan_plan_files(repo_root=tmp_path)

    assert branch_map == {}
    assert unresolved == []
