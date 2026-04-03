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
