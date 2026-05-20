from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DETECTOR = REPO_ROOT / "scripts" / "diagnostics" / "check-root-artifacts.ps1"


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


def _run_detector(repo: Path, json_output: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(DETECTOR),
    ]
    if json_output:
        cmd.append("-Json")
    return subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _run_hook(repo: Path) -> subprocess.CompletedProcess[str]:
    hook = repo / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook)],
        cwd=str(repo),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(tmp_path: Path, with_hook: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.name", "codex-artifact-guard"], repo)
    _run(["git", "config", "user.email", "codex-artifact-guard@example.com"], repo)
    (repo / ".gitignore").write_text(".tmp/\nlogs/\n", encoding="utf-8")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)

    if with_hook:
        git_hooks = repo / "scripts" / "git-hooks"
        diagnostics = repo / "scripts" / "diagnostics"
        git_hooks.mkdir(parents=True, exist_ok=True)
        diagnostics.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            REPO_ROOT / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1",
            git_hooks / "pre-commit-plans-block.ps1",
        )
        shutil.copy2(
            REPO_ROOT / "scripts" / "git-hooks" / "root-branch-guard.ps1",
            git_hooks / "root-branch-guard.ps1",
        )
        shutil.copy2(DETECTOR, diagnostics / "check-root-artifacts.ps1")
        _run(["git", "add", "scripts"], repo)
        _run(["git", "commit", "-m", "add hooks"], repo)

    return repo


def test_detector_flags_modernhouse_root_untracked_artifact(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "modernhouse-blog.png").write_bytes(b"png")

    result = _run_detector(repo, json_output=True)

    payload = json.loads(result.stdout)
    assert result.returncode != 0
    assert payload["artifactCount"] == 1
    assert payload["artifacts"][0]["path"] == "modernhouse-blog.png"
    assert payload["artifacts"][0]["classification"] == "modernhouse-browser-artifact"


def test_detector_allows_ignored_codex_browser_artifact_path(tmp_path):
    repo = _init_repo(tmp_path)
    artifact = repo / ".tmp" / "codex-browser-artifacts" / "sample.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"png")

    result = _run_detector(repo, json_output=True)

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["artifactCount"] == 0
    assert payload["artifacts"] == []


def test_detector_separates_unrelated_root_untracked_document(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "notes.md").write_text("not a browser artifact\n", encoding="utf-8")

    result = _run_detector(repo, json_output=True)

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["artifactCount"] == 0
    assert payload["unrelatedRootFiles"] == ["notes.md"]


def test_detector_returns_nonzero_for_snapshot_and_evidence_patterns(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "naver-popupstore-main-snapshot.md").write_text("# snapshot\n", encoding="utf-8")
    (repo / "naver-place-booking-evidence-20260518.json").write_text("{}", encoding="utf-8")

    result = _run_detector(repo, json_output=True)

    payload = json.loads(result.stdout)
    assert result.returncode != 0
    assert {item["path"] for item in payload["artifacts"]} == {
        "naver-popupstore-main-snapshot.md",
        "naver-place-booking-evidence-20260518.json",
    }


def test_precommit_hook_blocks_root_artifact_dirty(tmp_path):
    repo = _init_repo(tmp_path, with_hook=True)
    (repo / "browser-screenshot.png").write_bytes(b"png")
    (repo / "README.md").write_text("# fixture changed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)

    result = _run_hook(repo)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "codex_browser_artifact_root_dirty_detected" in output
    assert "browser-screenshot.png" in output


def test_precommit_hook_uses_existing_root_guard_after_artifact_removed(tmp_path):
    repo = _init_repo(tmp_path, with_hook=True)
    (repo / "app" / "worker.py").parent.mkdir(parents=True)
    (repo / "app" / "worker.py").write_text("implementation change\n", encoding="utf-8")
    _run(["git", "add", "app/worker.py"], repo)

    result = _run_hook(repo)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "codex_browser_artifact_root_dirty_detected" not in output
    assert "root_worktree_impl_scope_blocked" in output
