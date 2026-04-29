import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "git-hooks" / "install-post-merge-dirty-check.ps1"
WTOOLS_HOOK = Path(
    r"D:\work\project\service\wtools\common\tools\git-hooks\post-merge-dirty-check.ps1"
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _powershell(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if not exe:
        pytest.skip("PowerShell executable not found")
    return subprocess.run(
        [exe, "-ExecutionPolicy", "Bypass", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    fixture = repo / "tests" / "dev_runner" / "fixtures" / "test_plan_e2e_mock.md"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "# E2E Mock Plan\n"
        "> 생성일: 2026-02-27\n"
        "> 상태: 완료\n"
        "> branch: plan/test_plan_e2e_mock\n"
        "> worktree: .worktrees/test_plan_e2e_mock\n"
        "> 진행률: 1/1 (100%)\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def test_post_merge_hook_smoke_T3_meta_revival_blocked(tmp_path):
    """T3: fixture meta-line cleanup is whitelisted and auto-committed by the shared hook."""
    if not WTOOLS_HOOK.exists():
        pytest.skip(f"missing wtools hook script: {WTOOLS_HOOK}")
    repo = _init_repo(tmp_path)
    fixture = repo / "tests" / "dev_runner" / "fixtures" / "test_plan_e2e_mock.md"
    fixture.write_text(
        "# E2E Mock Plan\n"
        "> 생성일: 2026-02-27\n"
        "> 상태: 완료\n"
        "> 진행률: 1/1 (100%)\n",
        encoding="utf-8",
    )

    result = _powershell("-File", str(WTOOLS_HOOK), cwd=repo)

    assert result.returncode == 0, result.stderr + result.stdout
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    last = _git(repo, "log", "--oneline", "-1").stdout
    assert "chore: post-merge dirty cleanup" in last
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout
    assert "tests/dev_runner/fixtures/test_plan_e2e_mock.md" in committed.replace("\\", "/")


def test_post_merge_hook_smoke_T3_secret_dirty_blocks_run(tmp_path):
    """T3: secret-like dirty files fail fast and are not committed."""
    if not WTOOLS_HOOK.exists():
        pytest.skip(f"missing wtools hook script: {WTOOLS_HOOK}")
    repo = _init_repo(tmp_path)
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    result = _powershell("-File", str(WTOOLS_HOOK), cwd=repo)

    assert result.returncode != 0
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before
    assert ".env" in _git(repo, "status", "--porcelain").stdout
    assert "post-merge dirty blocked" in (result.stderr + result.stdout)


def test_install_post_merge_dirty_check_writes_absolute_wtools_wrapper(tmp_path):
    """R: monitor-page wrapper installs a Git hook that delegates to the wtools shared script."""
    if not INSTALLER.exists():
        pytest.skip(f"missing installer: {INSTALLER}")
    repo = _init_repo(tmp_path)

    result = _powershell("-File", str(INSTALLER), "-RepoRoot", str(repo), cwd=REPO_ROOT)

    assert result.returncode == 0, result.stderr + result.stdout
    hook = repo / ".git" / "hooks" / "post-merge"
    assert hook.exists()
    body = hook.read_text(encoding="utf-8")
    assert "GIT_HOOK_INVOKED" in body
    assert str(WTOOLS_HOOK) in body
