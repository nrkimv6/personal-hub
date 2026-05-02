import shutil
import subprocess

from tests.dev_runner import conftest_e2e
from tests.dev_runner.conftest_e2e import (
    TEST_PLAN_STEMS,
    FIXTURES_DIR,
    _cleanup_test_worktrees,
)

def test_fixture_files_match_stems():
    """R: TEST_PLAN_STEMS의 각 stem에 대해 fixtures/{stem}.md 존재 assert"""
    for stem in TEST_PLAN_STEMS:
        assert (FIXTURES_DIR / f"{stem}.md").exists(), f"fixture 누락: {stem}.md"

def test_fixture_no_stale_branch_fields():
    """B: 각 fixture .md 파일 내용에 '> branch:' / '> worktree:' 문자열 없음 assert"""
    # 이전 E2E 실행에서 남은 헤더 필드를 선정리해 실행 순서 의존성을 제거
    _cleanup_test_worktrees()
    for stem in TEST_PLAN_STEMS:
        content = (FIXTURES_DIR / f"{stem}.md").read_text(encoding="utf-8")
        assert "> branch:" not in content, f"stale branch field found in {stem}.md"
        assert "> worktree:" not in content, f"stale worktree field found in {stem}.md"

def test_cleanup_test_worktrees_is_idempotent():
    """B: worktree/branch 실제로 없는 상태에서 _cleanup_test_worktrees() 2회 호출해도 예외 없음 assert"""
    # 2회 연속 호출 - Exception 없이 완료되는지 확인
    _cleanup_test_worktrees()
    _cleanup_test_worktrees()


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_cleanup_test_worktrees_prunes_prunable_registration_and_runner_branch(tmp_path, monkeypatch):
    """T3: runner branch + prunable registration cleanup is idempotent in a real git repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    fixture = fixtures_dir / "test_minimal_plan.md"
    fixture.write_text(
        "# test\n> branch: runner/t-prunable-001\n> worktree: .worktrees/runner-prunable\n",
        encoding="utf-8",
    )

    worktree_base = repo / ".worktrees"
    prunable_path = worktree_base / "runner-prunable"
    _git(repo, "worktree", "add", "-b", "runner/t-prunable-001", str(prunable_path))
    shutil.rmtree(prunable_path)

    porcelain = _git(repo, "worktree", "list", "--porcelain").stdout
    assert "prunable" in porcelain
    assert "runner/t-prunable-001" in porcelain

    monkeypatch.setattr(conftest_e2e, "PROJECT_ROOT", repo)
    monkeypatch.setattr(conftest_e2e, "WORKTREE_BASE", worktree_base)
    monkeypatch.setattr(conftest_e2e, "FIXTURES_DIR", fixtures_dir)
    monkeypatch.setattr(conftest_e2e, "TEST_PLAN_STEMS", ["test_minimal_plan"])

    conftest_e2e._cleanup_test_worktrees()
    conftest_e2e._cleanup_test_worktrees()

    porcelain = _git(repo, "worktree", "list", "--porcelain").stdout
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
    fixture_content = fixture.read_text(encoding="utf-8")

    assert "prunable" not in porcelain
    assert "runner/t-prunable-001" not in branches
    assert "> branch:" not in fixture_content
    assert "> worktree:" not in fixture_content
