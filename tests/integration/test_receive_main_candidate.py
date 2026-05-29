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
    _run(["git", "config", "user.name", "receive-main-candidate"], repo)
    _run(["git", "config", "user.email", "receive-main-candidate@example.com"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "base.txt"], repo)
    _run(["git", "commit", "-m", "base"], repo)
    scripts = repo / "scripts"
    (scripts / "diagnostics").mkdir(parents=True)
    (scripts / "services").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / "diagnostics" / "check-candidate-tip.ps1", scripts / "diagnostics" / "check-candidate-tip.ps1")
    shutil.copy2(REPO_ROOT / "scripts" / "services" / "receive-main-candidate.ps1", scripts / "services" / "receive-main-candidate.ps1")
    return repo


def _receive(repo: Path, candidate: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "receive-main-candidate.ps1"),
            "-Candidate",
            candidate,
            "-Remote",
            ".",
            "-Branch",
            "main",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_receive_main_candidate_fast_forwards_local_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    feature_tip = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    _run(["git", "switch", "main"], repo)

    result = _receive(repo, "feature")

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "push_ready"
    assert payload["closeout_status"] == "push_required"
    assert payload["push_required"] is True
    assert payload["remote_aligned"] is False
    assert payload["post_receive_fetch_head"]["left"] == 1
    assert payload["post_receive_fetch_head"]["right"] == 0
    assert payload["post_receive_fetch_head"]["relation"] == "ahead-only"
    assert payload["remote_left"] == 1
    assert payload["remote_right"] == 0
    assert payload["remote_relation"] == "ahead-only"
    assert payload["head"] == feature_tip
    assert _run(["git", "rev-list", "--merges", "HEAD~1..HEAD"], repo).stdout.strip() == ""


def test_receive_main_candidate_reports_origin_main_alignment(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    remote = tmp_path / "origin.git"
    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "remote", "add", "origin", str(remote)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    _run(["git", "switch", "main"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "receive-main-candidate.ps1"),
            "-Candidate",
            "feature",
            "-Remote",
            "origin",
            "-Branch",
            "main",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["closeout_status"] == "push_required"
    assert payload["push_required"] is True
    assert payload["origin_main"]["available"] is True
    assert payload["origin_main"]["left"] == 1
    assert payload["origin_main"]["right"] == 0
    assert payload["origin_main"]["relation"] == "ahead-only"


def test_receive_main_candidate_push_required_prevents_late_mirror_closeout(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    remote = tmp_path / "origin.git"
    mirror = tmp_path / "mirror"
    _run(["git", "init", "--bare", str(remote)], tmp_path)
    _run(["git", "remote", "add", "origin", str(remote)], repo)
    _run(["git", "push", "-u", "origin", "main"], repo)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    _run(["git", "switch", "main"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "receive-main-candidate.ps1"),
            "-Candidate",
            "feature",
            "-Remote",
            "origin",
            "-Branch",
            "main",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["push_required"] is True

    _run(["git", "clone", "-b", "main", str(remote), str(mirror)], tmp_path)
    _run(["git", "config", "user.name", "mirror-sync"], mirror)
    _run(["git", "config", "user.email", "mirror-sync@example.com"], mirror)
    (mirror / "mirror.txt").write_text("mirror\n", encoding="utf-8")
    _run(["git", "add", "mirror.txt"], mirror)
    _run(["git", "commit", "-m", "mirror sync"], mirror)
    _run(["git", "push", "origin", "main"], mirror)
    _run(["git", "fetch", "origin", "main"], repo)

    assert _run(["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"], repo).stdout.strip() == "1\t1"


def test_receive_main_candidate_refuses_raw_merge_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "feature"], repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run(["git", "add", "feature.txt"], repo)
    _run(["git", "commit", "-m", "feature"], repo)
    _run(["git", "switch", "main"], repo)
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _run(["git", "add", "main.txt"], repo)
    _run(["git", "commit", "-m", "main advance"], repo)

    result = _receive(repo, "feature")

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "candidate_tip_guard_blocked" in output or "rebuild_needed" in output
    assert _run(["git", "rev-list", "--merges", "HEAD~1..HEAD"], repo).stdout.strip() == ""


def test_receive_main_candidate_requires_remote_receive_when_behind(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "remote-main"], repo)
    (repo / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run(["git", "add", "remote.txt"], repo)
    _run(["git", "commit", "-m", "remote advance"], repo)
    _run(["git", "switch", "main"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "receive-main-candidate.ps1"),
            "-Candidate",
            "main",
            "-Remote",
            ".",
            "-Branch",
            "remote-main",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 2
    assert "remote_receive_required" in result.stderr


def test_receive_main_candidate_stops_on_diverged_remote_state(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "remote-main"], repo)
    (repo / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run(["git", "add", "remote.txt"], repo)
    _run(["git", "commit", "-m", "remote advance"], repo)
    _run(["git", "switch", "main"], repo)
    (repo / "local.txt").write_text("local\n", encoding="utf-8")
    _run(["git", "add", "local.txt"], repo)
    _run(["git", "commit", "-m", "local advance"], repo)

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "services" / "receive-main-candidate.ps1"),
            "-Candidate",
            "main",
            "-Remote",
            ".",
            "-Branch",
            "remote-main",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 3
    assert "needs_explicit_merge_decision" in result.stderr
