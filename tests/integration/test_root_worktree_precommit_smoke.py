import shutil
import subprocess
from pathlib import Path


def _run(cmd, cwd):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def test_pre_commit_plans_block_rejects_main_plan_staging(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_src = Path(__file__).resolve().parents[2] / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"
    script = repo / "pre-commit-plans-block.ps1"
    shutil.copy(script_src, script)

    assert _run(["git", "init", "-b", "main"], repo).returncode == 0
    (repo / "docs" / "plan").mkdir(parents=True)
    (repo / "docs" / "plan" / "sample.md").write_text("# sample\n", encoding="utf-8")
    assert _run(["git", "add", "docs/plan/sample.md"], repo).returncode == 0

    result = _run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)], repo)

    assert result.returncode == 1
    assert "docs/plan" in ((result.stdout or "") + (result.stderr or ""))


def test_pre_commit_plans_block_allows_non_plan_staging(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    script_src = Path(__file__).resolve().parents[2] / "scripts" / "git-hooks" / "pre-commit-plans-block.ps1"
    script = repo / "pre-commit-plans-block.ps1"
    shutil.copy(script_src, script)

    assert _run(["git", "init", "-b", "main"], repo).returncode == 0
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    assert _run(["git", "add", "docs/guide.md"], repo).returncode == 0

    result = _run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)], repo)

    assert result.returncode == 0
