"""PlanService dual-path 실경로 재현 통합 TC (Phase T3)

tmp 파일시스템 기반 시나리오 — 등록 + dedupe + 경로 우선순위 end-to-end
"""
import json
import pytest
from pathlib import Path


PLAN_CONTENT = "# test plan\n\n> 상태: 구현중\n> 진행률: 0/1 (0%)\n\n- [ ] item1\n"
ARCHIVE_CONTENT = "# archived\n\n> 상태: 완료\n> 진행률: 1/1 (100%)\n\n- [x] done1\n"


@pytest.fixture
def dual_repo(tmp_path):
    """docs/plan + docs/archive + .worktrees/plans/docs/plan + .worktrees/plans/docs/archive 4축 repo"""
    dirs = {
        "docs_plan": tmp_path / "docs" / "plan",
        "docs_archive": tmp_path / "docs" / "archive",
        "wt_plan": tmp_path / ".worktrees" / "plans" / "docs" / "plan",
        "wt_archive": tmp_path / ".worktrees" / "plans" / "docs" / "archive",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    return tmp_path, dirs


class TestT3DualPathIntegration:
    """tmp repo에서 dual-path 실경로 재현 시나리오"""

    def test_register_all_four_roots_via_add_path(self, dual_repo, dev_runner_config_isolation):
        """등록 후 list_registered_paths() → 4개 루트 모두 노출"""
        _root, dirs = dual_repo
        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()

        assert svc.add_path(str(dirs["docs_plan"]), path_type="plan")
        assert svc.add_path(str(dirs["docs_archive"]), path_type="archive")
        assert svc.add_path(str(dirs["wt_plan"]), path_type="plan")
        assert svc.add_path(str(dirs["wt_archive"]), path_type="archive")

        registered = svc.list_registered_paths()
        assert len(registered) == 4, f"4개 루트 기대 — {len(registered)}개: {registered}"

        paths = [e.path for e in registered]
        assert any(".worktrees" not in p and "plan" in p for p in paths), "docs/plan 미포함"
        assert any(".worktrees" in p and "plan" in p for p in paths), "wt/plan 미포함"
        assert any(".worktrees" not in p and "archive" in p for p in paths), "docs/archive 미포함"
        assert any(".worktrees" in p and "archive" in p for p in paths), "wt/archive 미포함"

    def test_list_plans_prefers_worktree_when_both_exist(self, dual_repo, dev_runner_config_isolation):
        """동일 filename이 docs/plan과 wt/plan 양쪽에 있으면 wt/plan 경로만 list_plans에 노출"""
        _root, dirs = dual_repo
        cfg = dev_runner_config_isolation

        plan_file = "2026-01-01_shared.md"
        (dirs["docs_plan"] / plan_file).write_text(PLAN_CONTENT, encoding="utf-8")
        (dirs["wt_plan"] / plan_file).write_text(PLAN_CONTENT, encoding="utf-8")

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([
                {"path": str(dirs["docs_plan"]), "type": "plan"},
                {"path": str(dirs["wt_plan"]), "type": "plan"},
            ]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        plans = svc.list_plans()

        names = [p.filename for p in plans]
        assert names.count(plan_file) == 1, f"dedupe 실패 — {names.count(plan_file)}개 노출"
        match = next(p for p in plans if p.filename == plan_file)
        assert ".worktrees" in match.path, f"worktree 우선 실패 — {match.path}"

    def test_archive_roots_preserved_in_registered_paths(self, dual_repo, dev_runner_config_isolation):
        """archive 타입 경로도 registry에서 dedupe 없이 모두 보존된다"""
        _root, dirs = dual_repo
        cfg = dev_runner_config_isolation

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([
                {"path": str(dirs["docs_archive"]), "type": "archive"},
                {"path": str(dirs["wt_archive"]), "type": "archive"},
            ]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        registered = svc.list_registered_paths()
        archive_paths = [e.path for e in registered if e.path_type == "archive"]

        assert len(archive_paths) == 2, f"archive 루트 2개 기대 — {archive_paths}"
        assert any(".worktrees" in p for p in archive_paths), "wt/archive 미포함"
        assert any(".worktrees" not in p for p in archive_paths), "docs/archive 미포함"

    def test_list_registered_paths_not_affected_by_plan_dedupe(self, dual_repo, dev_runner_config_isolation):
        """list_registered_paths()는 list_plans dedupe와 무관하게 4개 루트를 전부 반환한다"""
        _root, dirs = dual_repo
        cfg = dev_runner_config_isolation

        plan_file = "2026-01-03_overlap.md"
        (dirs["docs_plan"] / plan_file).write_text(PLAN_CONTENT, encoding="utf-8")
        (dirs["wt_plan"] / plan_file).write_text(PLAN_CONTENT, encoding="utf-8")

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([
                {"path": str(dirs["docs_plan"]), "type": "plan"},
                {"path": str(dirs["docs_archive"]), "type": "archive"},
                {"path": str(dirs["wt_plan"]), "type": "plan"},
                {"path": str(dirs["wt_archive"]), "type": "archive"},
            ]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()

        registered = svc.list_registered_paths()
        assert len(registered) == 4, f"list_registered_paths 4개 기대 — {len(registered)}개"

        plans = svc.list_plans()
        names = [p.filename for p in plans]
        assert names.count(plan_file) == 1, f"list_plans dedupe 실패 — {names.count(plan_file)}개 노출"
