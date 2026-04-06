"""test_plan_worktree_meta_e2e.py — worktree 메타 E2E 통합 테스트

T4 시나리오:
- 실제 plan 파일에 worktree 헤더를 넣고 list_plans()로 파싱 검증
- 일반 plan은 3개 필드 모두 None
"""
import json
import textwrap
from pathlib import Path

import pytest

from app.modules.dev_runner.services.plan_service import PlanService


@pytest.fixture
def svc(tmp_path, dev_runner_config_isolation):
    cfg = dev_runner_config_isolation
    cfg.REGISTERED_PATHS_FILE = tmp_path / "registered_paths.json"
    cfg.IGNORED_PLANS_FILE = tmp_path / "ignored_plans.json"
    cfg.ALLOWED_PATHS = [str(tmp_path)]
    (tmp_path / "registered_paths.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ignored_plans.json").write_text("[]", encoding="utf-8")
    return PlanService()


def _make_plan_with_meta(plan_dir: Path, filename: str, branch: str, worktree: str, owner: str) -> Path:
    content = textwrap.dedent(f"""\
        # feat: {filename}

        > 상태: 구현중
        > 진행률: 3/5 (60%)
        > branch: {branch}
        > worktree: {worktree}
        > worktree-owner: {owner}

        ---

        ## TODO
        - [x] 항목 A
        - [x] 항목 B
        - [x] 항목 C
        - [ ] 항목 D
        - [ ] 항목 E
    """)
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _make_plain_plan(plan_dir: Path, filename: str) -> Path:
    content = textwrap.dedent("""\
        # feat: plain plan

        > 상태: 구현중
        > 진행률: 0/2 (0%)

        ## TODO
        - [ ] 항목 A
        - [ ] 항목 B
    """)
    p = plan_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


class TestWorktreeMetaE2E:

    def test_list_plans_includes_worktree_meta(self, svc, tmp_path):
        """R: worktree 헤더가 있는 plan → list_plans()에서 branch/worktree_path/worktree_owner 반환"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        branch = "impl/test-feature"
        worktree = ".worktrees/impl-test-feature"
        owner = "docs/plan/2026-04-06_test.md"

        _make_plan_with_meta(plan_dir, "2026-04-06_test.md", branch, worktree, owner)

        svc.add_path(str(plan_dir))
        plans = svc.list_plans()

        matching = [p for p in plans if "2026-04-06_test.md" in p.filename]
        assert len(matching) == 1, f"plan 미검색: {[p.filename for p in plans]}"
        plan = matching[0]

        assert plan.branch == branch
        assert plan.worktree_path == worktree
        assert plan.worktree_owner == owner

    def test_plain_plan_has_null_worktree_meta(self, svc, tmp_path):
        """R: worktree 헤더 없는 일반 plan → 3개 필드 모두 None"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        _make_plain_plan(plan_dir, "2026-04-06_plain.md")

        svc.add_path(str(plan_dir))
        plans = svc.list_plans()

        matching = [p for p in plans if "2026-04-06_plain.md" in p.filename]
        assert len(matching) == 1
        plan = matching[0]

        assert plan.branch is None
        assert plan.worktree_path is None
        assert plan.worktree_owner is None

    def test_worktree_owner_path_normalization(self, svc, tmp_path):
        """R: 백슬래시 절대경로 worktree-owner → 정규화된 상대경로로 반환"""
        plan_dir = tmp_path / "docs" / "plan"
        plan_dir.mkdir(parents=True)

        # 프로젝트 루트 절대경로 + 백슬래시 형식으로 worktree-owner 기록
        from pathlib import Path as _Path
        project_root = str(_Path(__file__).resolve().parents[2]).replace("/", "\\")
        raw_owner = f"{project_root}\\docs\\plan\\2026-04-06_test-norm.md"

        _make_plan_with_meta(
            plan_dir, "2026-04-06_test-norm.md",
            branch="impl/test-norm",
            worktree=".worktrees/impl-test-norm",
            owner=raw_owner,
        )

        svc.add_path(str(plan_dir))
        plans = svc.list_plans()

        matching = [p for p in plans if "2026-04-06_test-norm.md" in p.filename]
        assert len(matching) == 1
        plan = matching[0]

        # 정규화 결과: 백슬래시→슬래시, 절대경로→상대경로
        assert plan.worktree_owner is not None
        assert "\\" not in plan.worktree_owner, f"백슬래시 미정규화: {plan.worktree_owner}"
        assert not plan.worktree_owner.startswith("D:/"), f"절대경로 미정규화: {plan.worktree_owner}"
        assert "docs/plan/2026-04-06_test-norm.md" in plan.worktree_owner
