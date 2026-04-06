"""plan_service._extract_worktree_meta / _update_plan_headers / _validate_done_preconditions 단위 테스트"""
import pytest
from app.modules.dev_runner.services.plan_service import PlanService


# ─── _extract_worktree_meta ───────────────────────────────────────────────────

def test__extract_worktree_meta_right():
    """R(Right): 3개 필드 모두 포함 → 정확히 추출 + 정규화"""
    content = (
        "# plan title\n"
        "> 작성일시: 2026-04-06\n"
        "> 상태: 구현중\n"
        "> branch: impl/feature-name\n"
        "> worktree: .worktrees/impl-feature-name\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
    )
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] == "impl/feature-name"
    assert result["worktree_path"] == ".worktrees/impl-feature-name"
    assert result["worktree_owner"] == "docs/plan/2026-04-06_feature.md"


def test__extract_worktree_meta_empty():
    """B(Boundary): 메타 필드 없는 content → 3개 키 모두 None"""
    content = "# plan title\n> 상태: 초안\n\n---\n## 개요\n내용"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] is None
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_partial():
    """B(Boundary): branch만 있고 worktree-owner 없는 경우"""
    content = "# plan\n> branch: impl/feature\n> 상태: 구현중\n"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] == "impl/feature"
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_normalize():
    """R(Right): 다양한 경로 형식 → 동일 정규화 결과"""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/")

    # 백슬래시 절대경로
    content_backslash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root.replace('/', chr(92))}\\docs\\plan\\test.md\n"
    )
    result_bs = PlanService._extract_worktree_meta(content_backslash)

    # 슬래시 절대경로
    content_slash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root}/docs/plan/test.md\n"
    )
    result_sl = PlanService._extract_worktree_meta(content_slash)

    # 상대경로
    content_rel = (
        "> branch: impl/f\n"
        "> worktree: .worktrees/impl-f\n"
        "> worktree-owner: docs/plan/test.md\n"
    )
    result_rel = PlanService._extract_worktree_meta(content_rel)

    # 백슬래시와 슬래시 절대경로는 동일하게 정규화 (상대경로)
    assert result_bs["worktree_owner"] == result_sl["worktree_owner"]
    # 상대경로 입력은 그대로 유지
    assert result_rel["worktree_owner"] == "docs/plan/test.md"


# ─── _update_plan_headers ─────────────────────────────────────────────────────

def test__update_plan_headers_removes_worktree_owner():
    """R(Right): branch/worktree/worktree-owner 3줄 모두 제거됨"""
    content = (
        "# plan\n"
        "> 상태: 구현중\n"
        "> 진행률: 5/5 (100%)\n"
        "> branch: impl/feature\n"
        "> worktree: .worktrees/impl-feature\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
        "- [x] 항목1\n"
        "*상태: 구현중 | 진행률: 5/5 (100%)*\n"
    )
    result = PlanService._update_plan_headers(content, total=5)
    assert "branch" not in result or "> branch:" not in result
    assert "> worktree:" not in result
    assert "worktree-owner" not in result
    assert "구현완료" in result


# ─── _validate_done_preconditions ─────────────────────────────────────────────

def test__validate_done_preconditions_detects_worktree_owner():
    """E(Error): worktree-owner만 잔존해도 에러 감지"""
    content = (
        "# plan\n"
        "> 상태: 구현완료\n"
        "> 진행률: 5/5 (100%)\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
    )
    errors = PlanService._validate_done_preconditions("plan.md", content)
    assert any("branch/worktree" in e for e in errors), f"에러 미감지: {errors}"
