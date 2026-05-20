from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

fakeredis = pytest.importorskip("fakeredis")

PLAN_RUNNER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "root-dirty-closeout"], repo)
    _run(["git", "config", "user.email", "root-dirty-closeout@example.com"], repo)
    target = repo / "app" / "worker.py"
    target.parent.mkdir(parents=True)
    target.write_text("base\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _write_snapshot(snapshot_dir: Path, runner_id: str, repo: Path, *, dirty_files=None, owned_files=None) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "runner_id": runner_id,
        "project_root": str(repo),
        "dirty_files": dirty_files or [],
        "owned_files": owned_files or [],
        "clean_at_start_files": [],
    }
    (snapshot_dir / f"{runner_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_root_dirty_closeout_R_returns_reroute_required(monkeypatch, tmp_path):
    import _dr_merge

    repo = _init_repo(tmp_path)
    runner_id = "runner-root-dirty"
    snapshot_dir = tmp_path / "ownership"
    _write_snapshot(snapshot_dir, runner_id, repo)
    monkeypatch.setattr(_dr_merge, "OWNERSHIP_SNAPSHOT_DIR", snapshot_dir)

    (repo / "app" / "worker.py").write_text("root dirty\n", encoding="utf-8")
    messages: list[str] = []

    result = _dr_merge._check_post_merge_residue(runner_id, messages.append)

    assert result["success"] is False
    assert result["reason"] == "root_dirty_reroute_required"
    assert result["root_dirty_closeout_status"] == "reroute_required"
    assert result["root_dirty_paths"] == ["app/worker.py"]
    assert Path(result["reroute_required_path"]).exists()
    assert "app/worker.py" in _run(["git", "status", "--porcelain=v1"], repo).stdout


def test_root_dirty_closeout_OVERWRITE_reset_does_not_mark_success():
    from _dr_constants import ROOT_DIRTY_CLOSEOUT_STATUS_KEY, ROOT_DIRTY_STATUS_REROUTE_REQUIRED
    from _dr_merge_persistence import MergePersistence

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    persistence = MergePersistence(redis_client, "runner-overwrite")
    persistence.persist_result_metadata(
        {
            "success": False,
            "reason": "root_dirty_reroute_required",
            ROOT_DIRTY_CLOSEOUT_STATUS_KEY: ROOT_DIRTY_STATUS_REROUTE_REQUIRED,
            "reroute_required_path": "logs/dev_runner/reroute_required/runner.md",
        }
    )

    persistence.persist_result_metadata({"success": True, "message": "cleanup completed"})

    assert (
        redis_client.get("plan-runner:runners:runner-overwrite:root_dirty_closeout_status")
        == ROOT_DIRTY_STATUS_REROUTE_REQUIRED
    )


def test_root_dirty_closeout_PRESERVER_quarantine_diff_path_recorded(monkeypatch, tmp_path):
    import _dr_merge

    repo = _init_repo(tmp_path)
    runner_id = "runner-preserver"
    snapshot_dir = tmp_path / "ownership"
    _write_snapshot(snapshot_dir, runner_id, repo)
    monkeypatch.setattr(_dr_merge, "OWNERSHIP_SNAPSHOT_DIR", snapshot_dir)

    (repo / "scripts" / "tool.ps1").parent.mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "tool.ps1").write_text("Write-Output dirty\n", encoding="utf-8")

    result = _dr_merge._check_post_merge_residue(runner_id, lambda _msg: None)

    assert result["success"] is False
    assert result["quarantine_diff_path"]
    assert Path(result["quarantine_diff_path"]).exists()
    assert result["reroute_required_path"]
    assert Path(result["reroute_required_path"]).exists()
