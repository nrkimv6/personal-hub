"""plan_path_helpers 공유 헬퍼 단위 TC (Phase T1)

대상:
- backfill_dual_paths: 상호보완 경로 추가 / 이미 존재 시 no-op 검증
- dedupe_prefer_worktree: 동일 (repo_root, filename) 입력 시 worktree 경로 우선 선택 검증
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ========== backfill_dual_paths TC ==========

class TestBackfillDualPaths:
    """backfill_dual_paths 단위 TC"""

    def test_adds_worktree_path_when_only_docs_registered(self, tmp_path):
        """Right: docs 경로만 등록 + worktree 경로 실재 → worktree 경로 추가됨"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        entries = [{"path": str(docs_plan), "type": "plan"}]
        result, changed = backfill_dual_paths(entries)

        assert changed is True
        paths = [e["path"] for e in result]
        assert any(".worktrees" in p for p in paths), f"worktree 경로 없음: {paths}"
        assert len(result) == 2

    def test_adds_docs_path_when_only_worktree_registered(self, tmp_path):
        """Right: worktree 경로만 등록 + docs 경로 실재 → docs 경로 추가됨"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        entries = [{"path": str(wt_plan), "type": "plan"}]
        result, changed = backfill_dual_paths(entries)

        assert changed is True
        paths = [e["path"] for e in result]
        assert any(".worktrees" not in p for p in paths), f"docs 경로 없음: {paths}"

    def test_noop_when_both_paths_already_registered(self, tmp_path):
        """Boundary: 두 경로 모두 이미 등록 → changed=False, 목록 길이 동일"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        docs_plan = tmp_path / "docs" / "plan"
        wt_plan = tmp_path / ".worktrees" / "plans" / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        wt_plan.mkdir(parents=True)

        entries = [
            {"path": str(docs_plan.resolve()), "type": "plan"},
            {"path": str(wt_plan.resolve()), "type": "plan"},
        ]
        result, changed = backfill_dual_paths(entries)

        assert changed is False
        assert len(result) == 2

    def test_noop_when_counterpart_path_does_not_exist(self, tmp_path):
        """Boundary: 대응 경로가 실재하지 않으면 추가하지 않음"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        docs_plan = tmp_path / "docs" / "plan"
        docs_plan.mkdir(parents=True)
        # wt_plan 미생성 → backfill 대상 없음

        entries = [{"path": str(docs_plan), "type": "plan"}]
        result, changed = backfill_dual_paths(entries)

        assert changed is False
        assert len(result) == 1

    def test_empty_entries_returns_unchanged(self):
        """Boundary: 빈 목록 입력 → 빈 목록 반환, changed=False"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        result, changed = backfill_dual_paths([])

        assert result == []
        assert changed is False

    def test_unrecognized_path_pattern_skipped(self, tmp_path):
        """Boundary: extract_repo_root 추출 불가 경로 → 변경 없이 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        entries = [{"path": str(tmp_path / "some" / "random.md"), "type": "plan"}]
        result, changed = backfill_dual_paths(entries)

        assert changed is False
        assert result == entries

    def test_archive_type_backfill_independent_of_plan(self, tmp_path):
        """Right: type='archive' 경로도 같은 타입끼리만 backfill — plan 경로 추가 금지"""
        from app.modules.dev_runner.services.plan_path_helpers import backfill_dual_paths

        docs_archive = tmp_path / "docs" / "archive"
        wt_archive = tmp_path / ".worktrees" / "plans" / "docs" / "archive"
        docs_archive.mkdir(parents=True)
        wt_archive.mkdir(parents=True)

        entries = [{"path": str(docs_archive), "type": "archive"}]
        result, changed = backfill_dual_paths(entries)

        assert changed is True
        types = [e.get("type") for e in result]
        assert all(t == "archive" for t in types), f"plan 타입 혼입: {types}"


# ========== dedupe_prefer_worktree TC ==========

class TestDedupePreferWorktree:
    """dedupe_prefer_worktree 단위 TC"""

    def _make_plan_item(self, path: str, filename: str):
        """PlanFileResponse 유사 Mock 생성"""
        item = MagicMock()
        item.path = path
        item.filename = filename
        return item

    def test_prefers_worktree_path_over_docs_path(self, tmp_path):
        """Right: 동일 (repo_root, filename)에 docs+worktree 항목 → worktree 항목 선택"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        docs_path = str(tmp_path / "docs" / "plan" / "2026-01-01_test.md")
        wt_path = str(tmp_path / ".worktrees" / "plans" / "docs" / "plan" / "2026-01-01_test.md")
        filename = "2026-01-01_test.md"

        docs_item = self._make_plan_item(docs_path, filename)
        wt_item = self._make_plan_item(wt_path, filename)

        result = dedupe_prefer_worktree([docs_item, wt_item])

        assert len(result) == 1
        assert result[0].path == wt_path, f"worktree 경로가 선택되지 않음: {result[0].path}"

    def test_prefers_worktree_regardless_of_input_order(self, tmp_path):
        """Right: 입력 순서가 worktree 먼저여도 동일하게 worktree 선택"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        docs_path = str(tmp_path / "docs" / "plan" / "2026-01-01_test.md")
        wt_path = str(tmp_path / ".worktrees" / "plans" / "docs" / "plan" / "2026-01-01_test.md")
        filename = "2026-01-01_test.md"

        docs_item = self._make_plan_item(docs_path, filename)
        wt_item = self._make_plan_item(wt_path, filename)

        result = dedupe_prefer_worktree([wt_item, docs_item])

        assert len(result) == 1
        assert result[0].path == wt_path

    def test_single_item_no_dedup_needed(self, tmp_path):
        """Boundary: 항목 1개 → 그대로 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        docs_path = str(tmp_path / "docs" / "plan" / "2026-01-01_test.md")
        item = self._make_plan_item(docs_path, "2026-01-01_test.md")

        result = dedupe_prefer_worktree([item])

        assert len(result) == 1
        assert result[0] is item

    def test_different_filenames_not_deduped(self, tmp_path):
        """Boundary: 같은 repo_root이지만 다른 filename → 둘 다 유지"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        path_a = str(tmp_path / "docs" / "plan" / "2026-01-01_a.md")
        path_b = str(tmp_path / "docs" / "plan" / "2026-01-01_b.md")
        item_a = self._make_plan_item(path_a, "2026-01-01_a.md")
        item_b = self._make_plan_item(path_b, "2026-01-01_b.md")

        result = dedupe_prefer_worktree([item_a, item_b])

        assert len(result) == 2

    def test_unrecognized_path_preserved_as_ungrouped(self, tmp_path):
        """Boundary: extract_repo_root 실패 경로 → 삭제 없이 ungrouped로 보존"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        unknown_path = str(tmp_path / "some" / "random" / "plan.md")
        item = self._make_plan_item(unknown_path, "plan.md")

        result = dedupe_prefer_worktree([item])

        assert len(result) == 1
        assert result[0] is item

    def test_empty_list_returns_empty(self):
        """Boundary: 빈 목록 → 빈 목록 반환"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        result = dedupe_prefer_worktree([])

        assert result == []

    def test_two_repos_different_filenames_all_preserved(self, tmp_path):
        """Right: 서로 다른 repo의 동일 filename → 각자 독립 그룹, 모두 보존"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        path_a = str(repo_a / "docs" / "plan" / "2026-01-01_test.md")
        path_b = str(repo_b / "docs" / "plan" / "2026-01-01_test.md")
        item_a = self._make_plan_item(path_a, "2026-01-01_test.md")
        item_b = self._make_plan_item(path_b, "2026-01-01_test.md")

        result = dedupe_prefer_worktree([item_a, item_b])

        assert len(result) == 2

    def test_no_worktree_path_returns_first_item(self, tmp_path):
        """Boundary: 그룹 내 worktree 경로 없으면 첫 번째 항목 선택"""
        from app.modules.dev_runner.services.plan_path_helpers import dedupe_prefer_worktree

        path_1 = str(tmp_path / "docs" / "plan" / "2026-01-01_test.md")
        path_2 = str(tmp_path / "docs" / "plan" / "2026-01-01_test.md")
        filename = "2026-01-01_test.md"

        item_1 = self._make_plan_item(path_1, filename)
        item_2 = self._make_plan_item(path_2, filename)

        result = dedupe_prefer_worktree([item_1, item_2])

        assert len(result) == 1
        assert result[0] is item_1
