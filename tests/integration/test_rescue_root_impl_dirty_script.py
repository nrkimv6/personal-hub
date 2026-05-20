from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "rescue-root-impl-dirty.ps1"


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
    _run(["git", "config", "user.name", "root-dirty-rescue"], repo)
    _run(["git", "config", "user.email", "root-dirty-rescue@example.com"], repo)
    (repo / "app").mkdir()
    (repo / "app" / "worker.py").write_text("base\n", encoding="utf-8")
    (repo / ".claude" / "skills").mkdir(parents=True)
    (repo / ".claude" / "skills" / "SKILL.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _run_script(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(repo),
            *args,
        ],
        repo,
        check=check,
    )


def test_rescue_root_impl_dirty_dry_run_no_mutation(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app" / "worker.py").write_text("dirty\n", encoding="utf-8")

    result = _run_script(repo)

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "mode=dry-run" in output
    assert "implementation_path=app/worker.py" in output
    assert "dry_run_no_mutation=true" in output
    assert not (repo / ".worktrees").exists()
    assert _run(["git", "stash", "list"], repo).stdout.strip() == ""


def test_rescue_root_impl_dirty_apply_moves_impl_dirty_to_rescue_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app" / "worker.py").write_text("dirty\n", encoding="utf-8")

    result = _run_script(repo, "-Apply", "-RescueName", "codex/root-dirty-rescue-test")

    output = result.stdout + result.stderr
    rescue = repo / ".worktrees" / "codex-root-dirty-rescue-test"
    assert result.returncode == 0
    assert "root_clean_for_implementation=true" in output
    assert _run(["git", "status", "--porcelain=v1", "--", "app/worker.py"], repo).stdout.strip() == ""
    assert "app/worker.py" in _run(["git", "status", "--porcelain=v1"], rescue).stdout


def test_rescue_root_impl_dirty_apply_blocks_mirror_surface(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app" / "worker.py").write_text("dirty\n", encoding="utf-8")
    (repo / ".claude" / "skills" / "SKILL.md").write_text("mirror dirty\n", encoding="utf-8")

    result = _run_script(repo, "-Apply", "-RescueName", "codex/root-dirty-rescue-mirror", check=False)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "mirror surface dirty detected" in output
    assert "app/worker.py" in _run(["git", "status", "--porcelain=v1"], repo).stdout
