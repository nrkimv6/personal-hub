"""PlanService dual-path registry TC (Phase T1)

대상: plan_path_helpers, plan_service._backfill_dual_paths, _scan_all_plans dedupe
"""
import json
import pytest
from pathlib import Path


# ========== plan_path_helpers 단위 TC ==========

class TestPlanPathHelpers:
    """plan_path_helpers 모듈 단위 TC"""

    def test_iter_repo_plan_path_candidates_returns_four(self, tmp_path):
        """iter_repo_plan_path_candidates() → 4개 후보 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import iter_repo_plan_path_candidates
        candidates = iter_repo_plan_path_candidates(tmp_path)
        assert len(candidates) == 4
        types = [t for _, t in candidates]
        assert types.count("plan") == 2
        assert types.count("archive") == 2

    def test_extract_repo_root_from_worktree_path(self, tmp_path):
        """extract_repo_root_from_plan_path: .worktrees/plans/docs/plan/foo.md → repo root"""
        from app.modules.dev_runner.services.plan_path_helpers import extract_repo_root_from_plan_path
        plan_file = str(tmp_path / "repo" / ".worktrees" / "plans" / "docs" / "plan" / "foo.md")
        result = extract_repo_root_from_plan_path(plan_file)
        assert result == str(tmp_path / "repo")

    def test_extract_repo_root_from_docs_path(self, tmp_path):
        """extract_repo_root_from_plan_path: docs/plan/foo.md → repo root"""
        from app.modules.dev_runner.services.plan_path_helpers import extract_repo_root_from_plan_path
        plan_file = str(tmp_path / "repo" / "docs" / "plan" / "foo.md")
        result = extract_repo_root_from_plan_path(plan_file)
        assert result == str(tmp_path / "repo")

    def test_extract_repo_root_from_wtools_legacy_common_path(self, tmp_path, dev_runner_config_isolation):
        """Right: wtools/common/docs/plan/foo.md → repo root는 wtools여야 한다."""
        from app.modules.dev_runner.services.plan_path_helpers import extract_repo_root_from_plan_path
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        plan_file = str(cfg.WTOOLS_BASE_DIR / "common" / "docs" / "plan" / "foo.md")
        result = extract_repo_root_from_plan_path(plan_file)
        assert result == str(cfg.WTOOLS_BASE_DIR)

    def test_extract_repo_root_unknown_returns_none(self, tmp_path):
        """extract_repo_root_from_plan_path: 패턴 미일치 → None 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import extract_repo_root_from_plan_path
        result = extract_repo_root_from_plan_path(str(tmp_path / "some" / "random.md"))
        assert result is None

    def test_load_wtools_project_roots_returns_paths(self, tmp_path, dev_runner_config_isolation):
        """Right: .claude/projects.json 있으면 wtools root + project roots 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import load_wtools_project_roots
        cfg = dev_runner_config_isolation
        claude_dir = tmp_path / "wtools" / ".claude"
        claude_dir.mkdir(parents=True)
        repo1 = tmp_path / "wtools" / "proj1"
        repo2 = tmp_path / "wtools" / "proj2"
        data = {"projects": [
            {"name": "proj1", "path": str(repo1)},
            {"name": "proj2", "path": str(repo2)},
        ]}
        (claude_dir / "projects.json").write_text(json.dumps(data), encoding="utf-8")
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"

        roots = load_wtools_project_roots()
        assert len(roots) == 3
        assert cfg.WTOOLS_BASE_DIR in roots
        assert any("proj1" in str(r) for r in roots)
        assert any("proj2" in str(r) for r in roots)

    def test_load_wtools_project_roots_missing_returns_empty(self, tmp_path, dev_runner_config_isolation):
        """Boundary: .claude/projects.json 없으면 빈 목록 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import load_wtools_project_roots
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"  # .claude 없음

        roots = load_wtools_project_roots()
        assert roots == []


# ========== PlanService dual-path seed/backfill/dedupe TC ==========

class TestDualPathRegistry:

    @pytest.fixture
    def svc(self, dev_runner_config_isolation):
        from app.modules.dev_runner.services.plan_service import PlanService
        return PlanService()

    def test_normalize_registered_paths_dual_path_preserves_worktree_and_docs(self, tmp_path, svc):
        """Right: docs+worktree 두 경로가 모두 입력에 있으면 둘 다 보존된다."""
        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        entries = [
            {"path": str(docs_plan), "type": "plan"},
            {"path": str(wt_plan), "type": "plan"},
        ]
        normalized, _ = svc._normalize_registered_paths(entries)
        paths = [e["path"] for e in normalized]
        assert any(".worktrees" not in p for p in paths)
        assert any(".worktrees" in p for p in paths)

    def test_normalize_registered_paths_canonicalizes_wtools_legacy_common_root(self, tmp_path, svc, dev_runner_config_isolation):
        """Right: wtools/common/docs/plan 등록은 canonical plans worktree root로 치환된다."""
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        legacy_common = cfg.WTOOLS_BASE_DIR / "common" / "docs" / "plan"
        canonical_worktree = cfg.WTOOLS_BASE_DIR / ".worktrees" / "plans" / "docs" / "plan"
        legacy_common.mkdir(parents=True)
        canonical_worktree.mkdir(parents=True)

        normalized, changed = svc._normalize_registered_paths([{"path": str(legacy_common), "type": "plan"}])

        assert changed is True
        assert normalized == [{"path": str(canonical_worktree.resolve()), "type": "plan"}]

    def test_load_registered_paths_backfills_missing_worktree_path(self, tmp_path, dev_runner_config_isolation):
        """Right: 기존 registered_paths.json에 docs만 있어도 load 시 worktree 경로가 backfill된다."""
        cfg = dev_runner_config_isolation
        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([{"path": str(docs_plan), "type": "plan"}]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        paths = [e["path"] for e in svc._registered_paths]
        assert any(".worktrees" in p for p in paths), \
            f"worktree backfill 실패 — paths: {paths}"

    def test_seed_uses_claude_projects_json_when_present(self, tmp_path, dev_runner_config_isolation):
        """Right: .claude/projects.json 모킹 → 거기 있는 repo의 plan 경로가 시드된다."""
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        claude_dir = tmp_path / "wtools" / ".claude"
        claude_dir.mkdir(parents=True)
        repo_root = tmp_path / "wtools" / "my-project"
        plan_dir = repo_root / "docs" / "plan"
        root_worktree_plan_dir = cfg.WTOOLS_BASE_DIR / ".worktrees" / "plans" / "docs" / "plan"
        plan_dir.mkdir(parents=True)
        root_worktree_plan_dir.mkdir(parents=True)
        (claude_dir / "projects.json").write_text(
            json.dumps({"projects": [{"name": "my-project", "path": str(repo_root)}]}),
            encoding="utf-8",
        )
        cfg.REGISTERED_PATHS_FILE.unlink(missing_ok=True)

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        paths = [e["path"] for e in svc._registered_paths]
        assert any("my-project" in p for p in paths), \
            f"projects.json 기반 시드 실패 — paths: {paths}"
        assert any(str((cfg.WTOOLS_BASE_DIR / ".worktrees" / "plans" / "docs" / "plan").resolve()) == p for p in paths), \
            f"wtools root canonical seed 누락 — paths: {paths}"

    def test_seed_falls_back_when_claude_projects_json_missing(self, tmp_path, dev_runner_config_isolation):
        """Boundary: .claude/projects.json 미존재 → PROJECT_DIRS 기반 legacy fallback."""
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        cfg.PROJECT_DIRS = ["legacy-proj"]
        cfg.REGISTERED_PATHS_FILE.unlink(missing_ok=True)

        legacy_dir = tmp_path / "wtools" / "legacy-proj" / "docs" / "plan"
        legacy_dir.mkdir(parents=True)

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        paths = [e["path"] for e in svc._registered_paths]
        assert any("legacy-proj" in p for p in paths), \
            f"legacy fallback 실패 — paths: {paths}"

    def test_seed_skips_legacy_common_docs_plan(self, tmp_path, dev_runner_config_isolation):
        """E: common/docs/plan 같은 deprecated 경로는 시드되지 않는다 (projects.json 사용 시)."""
        cfg = dev_runner_config_isolation
        cfg.WTOOLS_BASE_DIR = tmp_path / "wtools"
        # .claude/projects.json 없음 → fallback이지만 PLAN_DIR 경로를 추가하지 않음
        # (새 구현은 iter_repo_plan_path_candidates 사용, common/docs/plan 추가 안 함)
        cfg.REGISTERED_PATHS_FILE.unlink(missing_ok=True)
        cfg.PROJECT_DIRS = []

        # common/docs/plan 생성해도 시드 안 됨
        (tmp_path / "wtools" / "common" / "docs" / "plan").mkdir(parents=True)

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        paths = [e["path"] for e in svc._registered_paths]
        # 새 구현은 common/docs/plan을 하드코딩 추가하지 않음
        # (wtools 루트의 docs/plan은 iter_repo_plan_path_candidates(wtools) 경유 시 추가 가능)
        # 여기서는 PROJECT_DIRS=[]이므로 wtools 루트 경로만 후보
        # common/ 하위는 무관
        assert not any("common" in p and "docs" in p and "plan" in p and ".worktrees" not in p
                        and p.endswith("docs" + "/" + "plan") for p in paths), \
            f"deprecated common/docs/plan이 시드에 포함됨: {paths}"

    def test_list_plans_dedupe_prefers_worktree_when_both_exist(self, tmp_path, dev_runner_config_isolation):
        """Cross-check: 동일 repo에서 docs와 worktree에 같은 filename이 있으면 worktree만 노출."""
        cfg = dev_runner_config_isolation
        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        plan_content = "# test plan\n\n> 상태: 구현중\n> 진행률: 0/0 (0%)\n"
        (docs_plan / "2026-01-01_test.md").write_text(plan_content, encoding="utf-8")
        (wt_plan / "2026-01-01_test.md").write_text(plan_content, encoding="utf-8")

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([
                {"path": str(docs_plan), "type": "plan"},
                {"path": str(wt_plan), "type": "plan"},
            ]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        plans = svc.list_plans()
        names = [p.filename for p in plans]
        assert names.count("2026-01-01_test.md") == 1, \
            f"dedupe 실패 — {names.count('2026-01-01_test.md')}개 노출"
        match = next(p for p in plans if p.filename == "2026-01-01_test.md")
        assert ".worktrees" in match.path, f"worktree 우선 dedupe 실패 — {match.path}"

    def test_list_registered_paths_returns_all_roots_independent_of_dedupe(self, tmp_path, dev_runner_config_isolation):
        """Cross-check: list_registered_paths()는 dedupe와 무관하게 등록된 4개 루트를 반환한다."""
        cfg = dev_runner_config_isolation
        for d in [
            tmp_path / "docs" / "plan",
            tmp_path / "docs" / "archive",
            tmp_path / ".worktrees" / "plans" / "docs" / "plan",
            tmp_path / ".worktrees" / "plans" / "docs" / "archive",
        ]:
            d.mkdir(parents=True)

        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([
                {"path": str(tmp_path / "docs" / "plan"), "type": "plan"},
                {"path": str(tmp_path / "docs" / "archive"), "type": "archive"},
                {"path": str(tmp_path / ".worktrees" / "plans" / "docs" / "plan"), "type": "plan"},
                {"path": str(tmp_path / ".worktrees" / "plans" / "docs" / "archive"), "type": "archive"},
            ]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        svc = PlanService()
        registered = svc.list_registered_paths()
        assert len(registered) == 4, f"등록된 루트 수 불일치 — {len(registered)}"

    def test_plan_path_registry_and_plan_service_share_registered_paths_file(self, tmp_path, dev_runner_config_isolation):
        """CORRECT/Reference: 두 모듈이 같은 registered_paths.json을 읽어 정규화 결과가 일치한다."""
        cfg = dev_runner_config_isolation
        docs_plan = tmp_path / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        cfg.REGISTERED_PATHS_FILE.write_text(
            json.dumps([{"path": str(docs_plan), "type": "plan"}]),
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.plan_service import PlanService
        from app.modules.dev_runner.services.plan_path_registry import PlanPathRegistry
        svc = PlanService()
        registry = PlanPathRegistry()

        svc_paths = {e["path"] for e in svc._registered_paths}
        reg_paths = {e["path"] for e in registry._registered_paths}
        # 둘 다 같은 파일을 읽으므로 공통 경로가 있어야 함
        assert svc_paths & reg_paths, \
            f"plan_service와 plan_path_registry의 등록 경로 불일치 — svc:{svc_paths} / reg:{reg_paths}"
