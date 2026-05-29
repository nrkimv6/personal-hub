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


def _init_duplicate_patch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "candidate-tip"], repo)
    _run(["git", "config", "user.email", "candidate-tip@example.com"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "base.txt"], repo)
    _run(["git", "commit", "-m", "base"], repo)
    _run(["git", "switch", "-c", "impl/stale"], repo)
    (repo / "feature.txt").write_text("same patch\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "original patch"], repo)
    _run(["git", "switch", "main"], repo)
    (repo / "feature.txt").write_text("same patch\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "rebased patch"], repo)
    return repo


def _copy_candidate_scripts(repo: Path) -> None:
    diagnostics = repo / "scripts" / "diagnostics"
    services = repo / "scripts" / "services"
    diagnostics.mkdir(parents=True, exist_ok=True)
    services.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "scripts" / "diagnostics" / "check-candidate-tip.ps1", diagnostics / "check-candidate-tip.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "services" / "pull-main-guarded.ps1", services / "pull-main-guarded.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "services" / "receive-main-candidate.ps1", services / "receive-main-candidate.ps1")


def _check_candidate(repo: Path, current: str = "main", candidate: str = "impl/stale") -> dict:
    script = REPO_ROOT / "scripts" / "diagnostics" / "check-candidate-tip.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-CurrentMain",
            current,
            "-CandidateTip",
            candidate,
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_candidate_tip_guard_reports_duplicate_patch_id_for_stale_branch(tmp_path: Path) -> None:
    repo = _init_duplicate_patch_repo(tmp_path)

    cherry = _run(["git", "cherry", "-v", "main", "impl/stale"], repo).stdout
    payload = _check_candidate(repo)

    assert cherry.startswith("- ")
    assert payload["duplicates"]
    assert payload["duplicates"][0]["subject"] == "original patch"
    assert "duplicate_patch_blocked" in payload["blockers"]
    assert "stale_ancestry_blocked" in payload["blockers"]


def test_candidate_tip_guard_blocks_duplicate_independent_of_ff_route(tmp_path: Path) -> None:
    repo = _init_duplicate_patch_repo(tmp_path)

    payload = _check_candidate(repo)

    assert payload["incoming_count"] == 1
    assert payload["merge_commits"] == []
    assert payload["duplicates"][0]["paths"] == ["feature.txt"]
    assert "duplicate_patch_blocked" in payload["blockers"]


def test_pull_main_guarded_blocks_duplicate_origin_tip(tmp_path: Path) -> None:
    repo = _init_duplicate_patch_repo(tmp_path)
    _copy_candidate_scripts(repo)
    _run(["git", "update-ref", "refs/remotes/origin/main", "impl/stale"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "pull-main-guarded.ps1"),
            "-Remote",
            ".",
            "-Branch",
            "impl/stale",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "candidate_tip_guard_blocked" in output
    assert "duplicate_patch_blocked" in output


def test_candidate_tip_receive_mode_keeps_incoming_merge_commit_blocker(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "candidate-tip"], repo)
    _run(["git", "config", "user.email", "candidate-tip@example.com"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "base.txt"], repo)
    _run(["git", "commit", "-m", "base"], repo)
    _run(["git", "switch", "-c", "side-a"], repo)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run(["git", "add", "a.txt"], repo)
    _run(["git", "commit", "-m", "a"], repo)
    _run(["git", "switch", "main"], repo)
    _run(["git", "switch", "-c", "side-b"], repo)
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _run(["git", "add", "b.txt"], repo)
    _run(["git", "commit", "-m", "b"], repo)
    _run(["git", "merge", "--no-ff", "side-a", "-m", "merge side-a"], repo)

    payload = _check_candidate(repo, current="main", candidate="side-b")

    assert payload["merge_commits"]
    assert "incoming_merge_commit_blocked" in payload["blockers"]
