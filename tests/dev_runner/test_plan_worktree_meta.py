"""plan_service._extract_worktree_meta / _update_plan_headers / _validate_done_preconditions ?⑥쐞 ?뚯뒪??"""
import pytest
from app.modules.dev_runner.services.plan_service import PlanService
from app.modules.dev_runner.services._plan_header_utils import validate_done_preconditions, update_plan_headers


# ??? _extract_worktree_meta ???????????????????????????????????????????????????

def test__extract_worktree_meta_right():
    """R(Right): 3媛??꾨뱶 紐⑤몢 ?ы븿 ???뺥솗??異붿텧 + ?뺢퇋??"""
    content = (
        "# plan title\n"
        "> created_at: 2026-04-06\n"
        "> status: in_progress\n"
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
    """B(Boundary): 硫뷀? ?꾨뱶 ?녿뒗 content ??3媛???紐⑤몢 None"""
    content = "# plan title\n> status: unknown\n\n---\n## overview\ncontent"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] is None
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_partial():
    """B(Boundary): branch留??덇퀬 worktree-owner ?녿뒗 寃쎌슦"""
    content = "# plan\n> branch: impl/feature\n> status: in_progress\n"
    result = PlanService._extract_worktree_meta(content)
    assert result["branch"] == "impl/feature"
    assert result["worktree_path"] is None
    assert result["worktree_owner"] is None


def test__extract_worktree_meta_normalize():
    """R(Right): ?ㅼ뼇??寃쎈줈 ?뺤떇 ???숈씪 ?뺢퇋??寃곌낵"""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/")

    # 諛깆뒳?섏떆 ?덈?寃쎈줈
    content_backslash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root.replace('/', chr(92))}\\docs\\plan\\test.md\n"
    )
    result_bs = PlanService._extract_worktree_meta(content_backslash)

    # ?щ옒???덈?寃쎈줈
    content_slash = (
        f"> branch: impl/f\n"
        f"> worktree: .worktrees/impl-f\n"
        f"> worktree-owner: {project_root}/docs/plan/test.md\n"
    )
    result_sl = PlanService._extract_worktree_meta(content_slash)

    # ?곷?寃쎈줈
    content_rel = (
        "> branch: impl/f\n"
        "> worktree: .worktrees/impl-f\n"
        "> worktree-owner: docs/plan/test.md\n"
    )
    result_rel = PlanService._extract_worktree_meta(content_rel)

    # 諛깆뒳?섏떆? ?щ옒???덈?寃쎈줈???숈씪?섍쾶 ?뺢퇋??(?곷?寃쎈줈)
    assert result_bs["worktree_owner"] == result_sl["worktree_owner"]
    # ?덈?寃쎈줈 ???곷?寃쎈줈 蹂??紐낆떆 寃利?
    assert result_bs["worktree_owner"] == "docs/plan/test.md", f"諛깆뒳?섏떆 ?덈?寃쎈줈?믪긽?寃쎈줈 蹂???ㅽ뙣: {result_bs['worktree_owner']}"
    assert result_sl["worktree_owner"] == "docs/plan/test.md", f"?щ옒???덈?寃쎈줈?믪긽?寃쎈줈 蹂???ㅽ뙣: {result_sl['worktree_owner']}"
    # ?곷?寃쎈줈 ?낅젰? 洹몃?濡??좎?
    assert result_rel["worktree_owner"] == "docs/plan/test.md"


# ??? _update_plan_headers ?????????????????????????????????????????????????????

def test__update_plan_headers_removes_worktree_owner():
    """R(Right): branch/worktree/worktree-owner 3以?紐⑤몢 ?쒓굅??"""
    content = (
        "# plan\n"
        "> status: in_progress\n"
        "> progress: 5/5 (100%)\n"
        "> branch: impl/feature\n"
        "> worktree: .worktrees/impl-feature\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
        "- [x] ??ぉ1\n"
        "*status: in_progress | progress: 5/5 (100%)*\n"
    )
    result = update_plan_headers(content, total=5)
    assert "branch" not in result or "> branch:" not in result
    assert "> worktree:" not in result
    assert "worktree-owner" not in result
    assert "in_progress" in result


# ??? _validate_done_preconditions ?????????????????????????????????????????????

def test__validate_done_preconditions_detects_worktree_owner():
    """E(Error): worktree-owner留??붿〈?대룄 ?먮윭 媛먯?"""
    content = (
        "# plan\n"
        "> status: completed\n"
        "> progress: 5/5 (100%)\n"
        "> worktree-owner: docs/plan/2026-04-06_feature.md\n"
        "\n---\n"
    )
    errors = validate_done_preconditions("plan.md", content)
    assert any("branch/worktree" in e for e in errors), f"?먮윭 誘멸컧吏: {errors}"


# ??? Phase 3 異붽? TC ?????????????????????????????????????????????????????????

def test__extract_worktree_meta_worktree_path_normalize():
    """R(Right): worktree ?꾨뱶瑜??덈?寃쎈줈濡??낅젰 ???곷?寃쎈줈濡?蹂?섎맖"""
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/")

    content = (
        f"> branch: impl/f\n"
        f"> worktree: {project_root}/.worktrees/impl-f\n"
        "> worktree-owner: docs/plan/test.md\n"
    )
    result = PlanService._extract_worktree_meta(content)
    assert result["worktree_path"] == ".worktrees/impl-f", (
        f"?덈?寃쎈줈 ???곷?寃쎈줈 蹂???ㅽ뙣: {result['worktree_path']}"
    )


def test_project_root_is_monitor_page_dir():
    """R(Right): config.PROJECT_ROOT ???꾨줈?앺듃 猷⑦듃 ?붾젆?좊━瑜?媛由ы궓??

    worktree ?댁뿉???ㅽ뻾 ??PROJECT_ROOT??worktree 猷⑦듃(=?꾨줈?앺듃 蹂듭궗蹂??대ŉ,
    癒몄? ??main?먯꽌??monitor-page ?붾젆?좊━媛 ?쒕떎.
    怨듯넻 寃利? PROJECT_ROOT???ㅼ젣 議댁옱?섎뒗 ?붾젆?좊━?닿퀬, app/ ?섏쐞 ?붾젆?좊━瑜?媛吏꾨떎.
    """
    from app.core.config import PROJECT_ROOT
    assert PROJECT_ROOT.exists(), f"PROJECT_ROOT 議댁옱?섏? ?딆쓬: {PROJECT_ROOT}"
    assert (PROJECT_ROOT / "app").exists(), f"PROJECT_ROOT/app ?놁쓬: {PROJECT_ROOT}"
    # monitor-page ?먮뒗 worktree ?붾젆?좊━紐??덉슜
    is_worktree = ".worktrees" in str(PROJECT_ROOT).replace("\\", "/")
    assert PROJECT_ROOT.name == "monitor-page" or is_worktree, (
        f"?덉긽移??딆? PROJECT_ROOT.name: '{PROJECT_ROOT.name}'"
    )


