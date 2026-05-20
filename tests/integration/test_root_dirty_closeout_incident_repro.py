from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLAN_RUNNER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(PLAN_RUNNER_DIR))


def _run(cmd: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "root-dirty-incident"], repo)
    _run(["git", "config", "user.email", "root-dirty-incident@example.com"], repo)
    target = repo / "app" / "worker.py"
    target.parent.mkdir(parents=True)
    target.write_text("base\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _write_snapshot(snapshot_dir: Path, runner_id: str, repo: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{runner_id}.json").write_text(
        json.dumps(
            {
                "runner_id": runner_id,
                "project_root": str(repo),
                "dirty_files": [],
                "owned_files": [],
                "clean_at_start_files": [],
            }
        ),
        encoding="utf-8",
    )


def test_root_dirty_closeout_incident_reset_leaves_reroute_required(monkeypatch, tmp_path):
    import _dr_merge

    repo = _init_repo(tmp_path)
    runner_id = "runner-reset-incident"
    snapshot_dir = tmp_path / "ownership"
    _write_snapshot(snapshot_dir, runner_id, repo)
    monkeypatch.setattr(_dr_merge, "OWNERSHIP_SNAPSHOT_DIR", snapshot_dir)

    target = repo / "app" / "worker.py"
    target.write_text("dirty from root closeout\n", encoding="utf-8")
    _run(["git", "add", "app/worker.py"], repo)
    _run(["git", "reset", "--", "app/worker.py"], repo)

    result = _dr_merge._check_post_merge_residue(runner_id, lambda _message: None)

    assert result["success"] is False
    assert result["reason"] == "root_dirty_reroute_required"
    assert result["root_dirty_closeout_status"] == "reroute_required"
    assert result["root_dirty_paths"] == ["app/worker.py"]
    assert Path(result["reroute_required_path"]).exists()
    assert "app/worker.py" in _run(["git", "status", "--porcelain=v1"], repo).stdout


def test_root_dirty_rescue_script_restores_root_clean_after_incident(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app" / "worker.py").write_text("dirty from root closeout\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "diagnostics" / "rescue-root-impl-dirty.ps1"

    result = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-RepoRoot",
            str(repo),
            "-Apply",
            "-RescueName",
            "codex/root-dirty-rescue-incident",
        ],
        repo,
    )

    rescue = repo / ".worktrees" / "codex-root-dirty-rescue-incident"
    output = result.stdout + result.stderr
    assert "root_clean_for_implementation=true" in output
    assert _run(["git", "status", "--porcelain=v1", "--", "app/worker.py"], repo).stdout.strip() == ""
    assert "app/worker.py" in _run(["git", "status", "--porcelain=v1"], rescue).stdout
