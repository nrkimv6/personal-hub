"""_plan_header_utils 단위 테스트 — validate_done_preconditions / update_plan_headers

RIGHT-BICEP 원칙 적용:
- Right: 정상 동작 검증
- Error/Edge: 예외 입력 처리 검증
"""
import pytest
from app.modules.dev_runner.services._plan_header_utils import (
    validate_done_preconditions,
    update_plan_headers,
)


# ─── validate_done_preconditions ─────────────────────────────────────────────

def test_validate_done_preconditions_clean_returns_empty():
    """R(Right): 정상 plan (branch/worktree 없음, non-fix) → [] 반환"""
    content = (
        "# refactor: 뭔가 개선\n"
        "> 상태: 구현완료\n"
        "> 진행률: 5/5 (100%)\n"
        "\n---\n"
        "## TODO\n"
        "- [x] 항목 1\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_refactor-something.md", content)
    assert errors == [], f"예상치 않은 에러: {errors}"


def test_validate_done_preconditions_worktree_residue():
    """E(Error): worktree-owner 잔존 → 에러 1개, 메시지에 'branch/worktree' 포함"""
    content = (
        "# refactor: 뭔가\n"
        "> 상태: 구현완료\n"
        "> worktree-owner: docs/plan/2026-04-01_refactor-something.md\n"
        "\n---\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_refactor-something.md", content)
    assert len(errors) >= 1
    assert any("branch/worktree" in e for e in errors)


def test_validate_done_preconditions_branch_residue():
    """E(Error): branch 필드 잔존 → 에러 반환"""
    content = (
        "# refactor: 뭔가\n"
        "> branch: impl/something\n"
        "> 상태: 구현완료\n"
        "\n---\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_refactor-something.md", content)
    assert len(errors) >= 1
    assert any("branch/worktree" in e for e in errors)


def test_validate_done_preconditions_fix_no_phase_r():
    """E(Error): _fix- 포함 파일명, Phase R 없음 → 에러 반환"""
    content = (
        "# fix: 뭔가 수정\n"
        "> 상태: 구현완료\n"
        "> 진행률: 3/3 (100%)\n"
        "\n---\n"
        "## TODO\n"
        "- [x] 항목 1\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_fix-something.md", content)
    assert len(errors) >= 1
    assert any("Phase R" in e for e in errors)


def test_validate_done_preconditions_fix_with_phase_r():
    """R(Right): fix plan + Phase R 섹션 있음 → []"""
    content = (
        "# fix: 뭔가 수정\n"
        "> 상태: 구현완료\n"
        "> 진행률: 3/3 (100%)\n"
        "\n---\n"
        "## TODO\n"
        "- [x] 항목 1\n"
        "\n### Phase R: 재발 경로 분석\n"
        "- 검토함: 없음\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_fix-something.md", content)
    assert errors == [], f"예상치 않은 에러: {errors}"


def test_validate_done_preconditions_fix_with_undefended_path():
    """E(Error): fix plan + Phase R 있지만 미방어 잔존 → 에러"""
    content = (
        "# fix: 뭔가 수정\n"
        "> 상태: 구현완료\n"
        "\n---\n"
        "\n### Phase R: 재발 경로 분석\n"
        "- 미방어: some_func\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_fix-something.md", content)
    assert len(errors) >= 1
    assert any("미방어" in e for e in errors)


def test_validate_done_preconditions_fix_via_title():
    """R(Right): 파일명에 _fix- 없어도 제목이 '# fix:' → fix plan 판정"""
    content = (
        "# fix: 뭔가 수정\n"
        "> 상태: 구현완료\n"
        "\n---\n"
        "\n### Phase R: 재발 경로 분석\n"
        "- 검토: 없음\n"
    )
    errors = validate_done_preconditions("docs/plan/2026-04-01_refactor-something.md", content)
    assert errors == [], f"예상치 않은 에러: {errors}"


# ─── update_plan_headers ────────────────────────────────────────────────────

def test_update_plan_headers_status_to_done():
    """R(Right): '> 상태: 구현중' → '> 상태: 구현완료' 변환"""
    content = "> 상태: 구현중\n내용"
    result = update_plan_headers(content, total=5)
    assert "> 상태: 구현완료" in result


def test_update_plan_headers_removes_worktree_fields():
    """R(Right): branch/worktree/worktree-owner 3줄 모두 제거됨"""
    content = (
        "# plan\n"
        "> 상태: 구현중\n"
        "> 진행률: 5/5 (100%)\n"
        "> branch: impl/feature\n"
        "> worktree: .worktrees/impl-feature\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
        "*상태: 구현중 | 진행률: 5/5 (100%)*\n"
    )
    result = update_plan_headers(content, total=5)
    assert "> branch:" not in result
    assert "> worktree:" not in result
    assert "worktree-owner" not in result
    assert "구현완료" in result


def test_update_plan_headers_progress_100():
    """R(Right): '> 진행률: 3/5 (60%)' → '> 진행률: 7/7 (100%)' (total=7)"""
    content = "> 상태: 구현중\n> 진행률: 3/5 (60%)\n내용"
    result = update_plan_headers(content, total=7)
    assert "> 진행률: 7/7 (100%)" in result


def test_update_plan_headers_arrow_id_to_x():
    """R(Right): [→TODO], [→P1] 형태 → [x] 변환"""
    content = "1. [→TODO] 항목\n2. [→P1] 항목2"
    result = update_plan_headers(content, total=2)
    assert "[→TODO]" not in result
    assert "[→P1]" not in result
    assert result.count("[x]") == 2


def test_update_plan_headers_footer_updated():
    """R(Right): 푸터 *상태: ... | 진행률: ...* 갱신됨"""
    content = "내용\n*상태: 구현중 | 진행률: 3/5 (60%)*"
    result = update_plan_headers(content, total=5)
    assert "*상태: 구현완료 | 진행률: 5/5 (100%)*" in result


# ─── Phase T3: 직접 import 통합 검증 ────────────────────────────────────────

def test_direct_import_from_utils_module():
    """T3(Integration): _plan_header_utils 직접 import 성공 + 기본 동작 검증"""
    from app.modules.dev_runner.services._plan_header_utils import (
        validate_done_preconditions as vdc,
        update_plan_headers as uph,
    )
    # import 성공 검증
    assert callable(vdc)
    assert callable(uph)

    # 동일 입력에 대한 단독 동작 검증
    content = "> 상태: 구현중\n내용"
    result = uph(content, total=3)
    assert "> 상태: 구현완료" in result

    errors = vdc("clean.md", "> 상태: 구현완료\n내용")
    assert errors == []
