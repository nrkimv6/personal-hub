"""
done 사전 검증 함수 단위 테스트

대상 함수 (plan_worktree_helpers.py):
- is_fix_plan()
- has_phase_r()
- has_undefended_paths()
- validate_done_preconditions()
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# scripts/ 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from plan_worktree_helpers import (
    is_fix_plan,
    has_phase_r,
    has_undefended_paths,
    validate_done_preconditions,
)

# app/ 경로 추가 (plan_service 테스트용)
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


# ---------------------------------------------------------------------------
# is_fix_plan
# ---------------------------------------------------------------------------

class TestIsFixPlan:
    def test_filename_fix_dash(self):
        """_fix- 포함 파일명 → True"""
        assert is_fix_plan("docs/plan/2026-03-31_fix-done-premature.md") is True

    def test_filename_fix_underscore(self):
        """_fix_ 포함 파일명 → True"""
        assert is_fix_plan("docs/plan/2026-03-31_fix_something.md") is True

    def test_title(self):
        """# fix: ... 제목 → True"""
        content = "# fix: done 완료 처리 사전 검증 누락\n\n> 상태: 초안\n"
        assert is_fix_plan("docs/plan/2026-03-31_something.md", content) is True

    def test_header_type(self):
        """> 유형: fix 헤더 → True"""
        content = "# 뭔가\n\n> 유형: fix\n> 상태: 초안\n"
        assert is_fix_plan("docs/plan/2026-03-31_something.md", content) is True

    def test_negative(self):
        """fix 없는 파일명 + 내용 → False"""
        content = "# feat: 새 기능\n\n> 유형: feat\n"
        assert is_fix_plan("docs/plan/2026-03-31_feat-new-feature.md", content) is False


# ---------------------------------------------------------------------------
# has_phase_r
# ---------------------------------------------------------------------------

class TestHasPhaseR:
    def test_present(self):
        """'Phase R' 포함 → True"""
        content = "## TODO\n\n### Phase R: 재발 경로 분석\n\n방어됨\n"
        assert has_phase_r(content) is True

    def test_korean(self):
        """'재발 경로 분석' 포함 → True"""
        content = "## 재발 경로 분석\n\n방어됨\n"
        assert has_phase_r(content) is True

    def test_absent(self):
        """없으면 False"""
        content = "## TODO\n\n### Phase 1: 구현\n\n- [ ] 뭔가\n"
        assert has_phase_r(content) is False


# ---------------------------------------------------------------------------
# has_undefended_paths
# ---------------------------------------------------------------------------

class TestHasUndefendedPaths:
    def test_undefended_in_phase_r(self):
        """Phase R 내 '미방어' → True"""
        content = (
            "### Phase R: 재발 경로 분석\n\n"
            "| 경로 | 방어여부 |\n"
            "| path1 | 미방어 |\n"
            "\n### 다른 섹션\n"
        )
        assert has_undefended_paths(content) is True

    def test_undefended_in_codeblock_ignored(self):
        """코드블럭 내 '미방어' → 무시 → False"""
        content = (
            "### Phase R: 재발 경로 분석\n\n"
            "모든 경로 방어됨\n"
            "```\n미방어 예시\n```\n"
            "\n### 다른 섹션\n"
        )
        assert has_undefended_paths(content) is False

    def test_all_defended(self):
        """'방어됨'만 있으면 False"""
        content = (
            "### Phase R: 재발 경로 분석\n\n"
            "| 경로 | 방어여부 |\n"
            "| path1 | 방어됨 |\n"
            "\n### 다른 섹션\n"
        )
        assert has_undefended_paths(content) is False


# ---------------------------------------------------------------------------
# validate_done_preconditions
# ---------------------------------------------------------------------------

class TestValidateDonePreconditions:
    def test_fix_no_phase_r(self):
        """fix plan + Phase R 없음 → 에러 사유 반환"""
        content = "# fix: 뭔가\n\n> 상태: 구현중\n\n## TODO\n- [x] 뭔가\n"
        errors = validate_done_preconditions(
            "docs/plan/2026-03-31_fix-something.md", content
        )
        assert len(errors) == 1
        assert "Phase R" in errors[0]

    def test_fix_undefended(self):
        """fix plan + Phase R '미방어' → 에러 사유 반환"""
        content = (
            "# fix: 뭔가\n\n> 상태: 구현중\n\n"
            "### Phase R: 재발 경로 분석\n\n"
            "| 경로 | 방어여부 |\n| path1 | 미방어 |\n"
            "\n### 다른\n"
        )
        errors = validate_done_preconditions(
            "docs/plan/2026-03-31_fix-something.md", content
        )
        assert len(errors) == 1
        assert "미방어" in errors[0]

    def test_branch_field(self):
        """branch 필드 잔존 → 에러 사유 반환"""
        content = "# feat: 뭔가\n\n> 상태: 구현중\n> branch: impl/foo\n"
        errors = validate_done_preconditions(
            "docs/plan/2026-03-31_feat-something.md", content
        )
        assert len(errors) == 1
        assert "branch" in errors[0]

    def test_fix_with_phase_r_defended(self):
        """fix plan + Phase R + 전부 방어됨 → 빈 리스트"""
        content = (
            "# fix: 뭔가\n\n> 상태: 구현중\n\n"
            "### Phase R: 재발 경로 분석\n\n"
            "| 경로 | 방어여부 |\n| path1 | 방어됨 |\n"
            "\n### 다른\n"
        )
        errors = validate_done_preconditions(
            "docs/plan/2026-03-31_fix-something.md", content
        )
        assert errors == []

    def test_non_fix(self):
        """fix 아닌 plan → Phase R 무관 통과"""
        content = "# feat: 새 기능\n\n> 상태: 구현중\n\n## TODO\n- [x] 뭔가\n"
        errors = validate_done_preconditions(
            "docs/plan/2026-03-31_feat-something.md", content
        )
        assert errors == []


# ---------------------------------------------------------------------------
# run_done API 검증 (plan_service._validate_done_preconditions)
# ---------------------------------------------------------------------------

class TestRunDoneRejectsFixWithoutPhaseR:
    """run_done API에서 fix plan + Phase R 없음 → ValueError"""

    def test_plan_service_validate(self):
        """plan_service._validate_done_preconditions이 fix plan Phase R 없음을 거부"""
        from app.modules.dev_runner.services.plan_service import PlanService
        content = "# fix: 뭔가\n\n> 상태: 구현중\n\n## TODO\n- [x] 뭔가\n"
        errors = PlanService._validate_done_preconditions(
            "docs/plan/2026-03-31_fix-something.md", content
        )
        assert len(errors) >= 1
        assert any("Phase R" in e for e in errors)

    def test_plan_done_service_validate(self):
        """plan_done_service._validate_done_preconditions이 fix plan Phase R 없음을 거부"""
        from app.modules.dev_runner.services.plan_done_service import PlanDoneService
        content = "# fix: 뭔가\n\n> 상태: 구현중\n\n## TODO\n- [x] 뭔가\n"
        errors = PlanDoneService._validate_done_preconditions(
            "docs/plan/2026-03-31_fix-something.md", content
        )
        assert len(errors) >= 1
        assert any("Phase R" in e for e in errors)


# ---------------------------------------------------------------------------
# T3: _handle_post_merge_done 통합 TC (근본 원인 재현)
# ---------------------------------------------------------------------------

class TestHandlePostMergeDoneFixNoPhaseR:
    """_handle_post_merge_done에 fix plan(Phase R 없음) 전달 시
    상태가 구현완료로 변경되지 않음을 검증 (근본 원인 재현)"""

    def test_fix_plan_no_phase_r_blocks_transition(self, tmp_path):
        """fix plan + Phase R 없음 → 구현완료 전이 스킵"""
        from _dr_merge import _handle_post_merge_done

        # fix plan 파일 생성 (머지대기 상태, Phase R 없음)
        plan_file = tmp_path / "2026-03-31_fix-something.md"
        plan_file.write_text(
            "# fix: 뭔가\n\n> 상태: 머지대기\n> 진행률: 5/5 (100%)\n\n"
            "## TODO\n- [x] 뭔가\n\n*상태: 머지대기 | 진행률: 5/5 (100%)*\n",
            encoding="utf-8",
        )

        logs = []
        pub_fn = lambda msg: logs.append(msg)
        mock_redis = Mock()

        # get_plan_completion mock (100%)
        with patch("plan_worktree_helpers.get_plan_completion", return_value=(5, 5)), \
             patch("_dr_merge._call_done_api", return_value=True):
            _handle_post_merge_done(str(plan_file), "runner-test", pub_fn, mock_redis)

        # 상태가 구현완료로 변경되지 않아야 함
        result = plan_file.read_text(encoding="utf-8")
        assert "구현완료" not in result
        assert "머지대기" in result
        # 로그에 사전 검증 실패 메시지
        assert any("Phase R" in log for log in logs)


class TestArchivePathParity:
    """PlanService/PlanDoneService archive/history target 경로 패리티."""

    @pytest.mark.asyncio
    async def test_common_docs_plan_parity(self, tmp_path):
        from app.modules.dev_runner.services.plan_service import PlanService
        from app.modules.dev_runner.services.plan_done_service import PlanDoneService

        ps_plan = tmp_path / "svc1" / "common" / "docs" / "plan" / "2026-04-03_fix.md"
        pd_plan = tmp_path / "svc2" / "common" / "docs" / "plan" / "2026-04-03_fix.md"
        ps_plan.parent.mkdir(parents=True)
        pd_plan.parent.mkdir(parents=True)
        ps_plan.write_text("# t\n> 상태: 구현완료\n", encoding="utf-8")
        pd_plan.write_text("# t\n> 상태: 구현완료\n", encoding="utf-8")

        svc = PlanService.__new__(PlanService)
        scanner = Mock()
        scanner._find_todo_file.return_value = None
        done_svc = PlanDoneService(scanner=scanner, registry=Mock())

        ps_archive, _ = await svc._archive_plan(str(ps_plan), ps_plan.read_text(encoding="utf-8"))
        pd_archive, _ = await done_svc._archive_plan(str(pd_plan), pd_plan.read_text(encoding="utf-8"))

        assert ps_archive.parts[-3:] == ("docs", "archive", "2026-04-03_fix.md")
        assert pd_archive.parts[-3:] == ("docs", "archive", "2026-04-03_fix.md")

    @pytest.mark.asyncio
    async def test_auto_plan_history_parity(self, tmp_path):
        from app.modules.dev_runner.services.plan_service import PlanService
        from app.modules.dev_runner.services.plan_done_service import PlanDoneService

        ps_plan = tmp_path / "svc1" / "docs" / "plan" / "2026-04-03_auto-next.md"
        pd_plan = tmp_path / "svc2" / "docs" / "plan" / "2026-04-03_auto-next.md"
        ps_plan.parent.mkdir(parents=True)
        pd_plan.parent.mkdir(parents=True)
        ps_plan.write_text("# t\n> 상태: 구현완료\n", encoding="utf-8")
        pd_plan.write_text("# t\n> 상태: 구현완료\n", encoding="utf-8")

        svc = PlanService.__new__(PlanService)
        scanner = Mock()
        scanner._find_todo_file.return_value = None
        done_svc = PlanDoneService(scanner=scanner, registry=Mock())

        ps_archive, _ = await svc._archive_plan(str(ps_plan), ps_plan.read_text(encoding="utf-8"))
        pd_archive, _ = await done_svc._archive_plan(str(pd_plan), pd_plan.read_text(encoding="utf-8"))

        assert ps_archive.parts[-3:] == ("docs", "history", "2026-04-03_auto-next.md")
        assert pd_archive.parts[-3:] == ("docs", "history", "2026-04-03_auto-next.md")
