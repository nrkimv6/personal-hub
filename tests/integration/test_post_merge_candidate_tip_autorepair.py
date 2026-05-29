from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise AssertionError(f"{cmd} failed\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "post-merge-repair"], repo)
    _run(["git", "config", "user.email", "post-merge-repair@example.com"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "base.txt"], repo)
    _run(["git", "commit", "-m", "base"], repo)
    scripts = repo / "scripts"
    (scripts / "diagnostics").mkdir(parents=True)
    (scripts / "git-hooks").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "diagnostics" / "check-candidate-tip.ps1", scripts / "diagnostics" / "check-candidate-tip.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "git-hooks" / "post-merge-candidate-tip-check.ps1", scripts / "git-hooks" / "post-merge-candidate-tip-check.ps1")
    return repo


def _hook(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "git-hooks" / "post-merge-candidate-tip-check.ps1"),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _sentinel(repo: Path) -> Path:
    path = Path(_run(["git", "rev-parse", "--git-path", "candidate-tip-violation.json"], repo).stdout.strip())
    if path.is_absolute():
        return path
    return repo / path


def test_candidate_tip_post_merge_mode_reports_repairable_merge_without_receive_blocker(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    _run(["git", "switch", "main"], repo)
    _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "diagnostics" / "check-candidate-tip.ps1"),
            "-CurrentMain",
            "ORIG_HEAD",
            "-CandidateTip",
            "HEAD",
            "-Mode",
            "PostMergeRepair",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "PostMergeRepair"
    assert payload["merge_commits"]
    assert payload["repairable_merge_commits"]
    assert "incoming_merge_commit_blocked" not in payload["blockers"]


def test_post_merge_hook_refuses_reset_hard_repair() -> None:
    hook_text = (REPO_ROOT / "scripts" / "git-hooks" / "post-merge-candidate-tip-check.ps1").read_text(encoding="utf-8")

    assert "reset --hard" not in hook_text


def test_post_merge_hook_linearizes_simple_merge_commit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    feature_tip = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    _run(["git", "switch", "main"], repo)
    _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], repo)
    merge_commit = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    assert merge_commit != feature_tip

    result = _hook(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "linearization_applied" in result.stdout
    assert _run(["git", "rev-parse", "HEAD"], repo).stdout.strip() == feature_tip
    assert _run(["git", "rev-list", "--merges", f"{base}..HEAD"], repo).stdout.strip() == ""
    assert not _sentinel(repo).exists()


def test_post_merge_hook_reports_repair_required_when_reset_hard_free_linearization_is_unavailable(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    _run(["git", "switch", "main"], repo)
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _run(["git", "add", "main.txt"], repo)
    _run(["git", "commit", "-m", "main advance"], repo)
    _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], repo)
    merge_commit = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()

    result = _hook(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "post_merge_candidate_tip_repair_required" in result.stderr
    assert _run(["git", "rev-parse", "HEAD"], repo).stdout.strip() == merge_commit
    sentinel = _sentinel(repo)
    assert sentinel.exists()
    payload = json.loads(sentinel.read_text(encoding="utf-8-sig"))
    assert payload["status"] == "repair_required"


def test_post_merge_hook_removes_stale_violation_sentinel_after_repair(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    feature_tip = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    _run(["git", "switch", "main"], repo)
    _run(["git", "merge", "--no-ff", "feature", "-m", "merge feature"], repo)
    sentinel = _sentinel(repo)
    sentinel.write_text('{"candidate_tip":"stale"}', encoding="utf-8")

    result = _hook(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _run(["git", "rev-parse", "HEAD"], repo).stdout.strip() == feature_tip
    assert not sentinel.exists()
