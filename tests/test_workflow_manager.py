"""
WorkflowManager 단위 테스트

Phase T1 TC:
  - test_workflow_manager_create_and_get: R(Right) — create + get_by_slug
  - test_workflow_manager_update_status: R(Right) — update_status + 타임스탬프
  - test_workflow_manager_list_filter: R(Right) — list_workflows 필터링
  - test_workflow_manager_boundary_empty_db: B(Boundary) — 빈 DB
  - test_workflow_manager_boundary_get_nonexistent: B(Boundary) — 없는 runner_id
  - test_workflow_manager_error_duplicate_create: E(Error) — slug 중복
"""
import pytest
import sqlite3
from pathlib import Path
import tempfile
import os
from sqlalchemy.exc import IntegrityError

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from workflow_manager import WorkflowManager


@pytest.fixture
def wf_manager(tmp_path):
    """임시 SQLite DB + workflows 테이블 초기화"""
    db_path = tmp_path / "test_workflow.db"
    # 테이블 생성
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT    NOT NULL UNIQUE,
            plan_file   TEXT,
            branch      TEXT,
            runner_id   TEXT,
            status      TEXT    NOT NULL DEFAULT 'planned',
            engine      TEXT,
            error_message TEXT,
            commit_hash TEXT,
            worktree_path TEXT,
            created_at  TEXT,
            started_at  TEXT,
            merged_at   TEXT,
            finished_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    return WorkflowManager(db_path)


def test_workflow_manager_create_and_get(wf_manager):
    """R(Right): create(slug, plan_file) → get_by_slug(slug) → 동일 레코드 반환"""
    wf_id = wf_manager.create("test-slug", "docs/plan/test.md")
    assert isinstance(wf_id, int)
    assert wf_id > 0

    result = wf_manager.get_by_slug("test-slug")
    assert result is not None
    assert result["slug"] == "test-slug"
    assert result["plan_file"] == "docs/plan/test.md"
    assert result["status"] == "planned"


def test_workflow_manager_update_status(wf_manager):
    """R(Right): create → update_status(id, "running", runner_id="abc") → 상태 및 타임스탬프 변경"""
    wf_id = wf_manager.create("test-update", "docs/plan/test.md")

    wf_manager.update_status(wf_id, "running", runner_id="runner-abc", branch="plan/test")
    result = wf_manager.get_by_slug("test-update")

    assert result["status"] == "running"
    assert result["runner_id"] == "runner-abc"
    assert result["branch"] == "plan/test"
    assert result["started_at"] is not None


def test_workflow_manager_list_filter(wf_manager):
    """R(Right): 3개 레코드(planned, running, completed) 생성 → list_workflows 필터 확인"""
    id1 = wf_manager.create("slug-planned", None)
    id2 = wf_manager.create("slug-running", None)
    id3 = wf_manager.create("slug-completed", None)

    wf_manager.update_status(id2, "running")
    wf_manager.update_status(id3, "completed")

    all_wf = wf_manager.list_workflows()
    assert len(all_wf) == 3

    running_wf = wf_manager.list_workflows(status="running")
    assert len(running_wf) == 1
    assert running_wf[0]["slug"] == "slug-running"

    completed_wf = wf_manager.list_workflows(status="completed")
    assert len(completed_wf) == 1
    assert completed_wf[0]["slug"] == "slug-completed"
    assert completed_wf[0]["finished_at"] is not None


def test_workflow_manager_boundary_empty_db(wf_manager):
    """B(Boundary): 빈 DB에서 list_workflows() → 빈 리스트, get_by_slug("x") → None"""
    result = wf_manager.list_workflows()
    assert result == []

    result = wf_manager.get_by_slug("nonexistent")
    assert result is None


def test_workflow_manager_boundary_get_nonexistent(wf_manager):
    """B(Boundary): 존재하지 않는 runner_id로 get_by_runner_id() → None"""
    result = wf_manager.get_by_runner_id("no-such-runner")
    assert result is None


def test_workflow_manager_error_duplicate_create(wf_manager):
    """E(Error): 동일 slug로 create() 2회 → sqlite3.IntegrityError 발생"""
    wf_manager.create("duplicate", None)

    with pytest.raises(IntegrityError):
        wf_manager.create("duplicate", None)


def test_workflow_manager_slug_from_plan_file():
    """R(Right): _slug_from_plan_file — _todo 접미사 제거"""
    assert WorkflowManager._slug_from_plan_file("docs/plan/2026-03-03_workflow-manager_todo.md") == "2026-03-03_workflow-manager"
    assert WorkflowManager._slug_from_plan_file("2026-01-01_feature.md") == "2026-01-01_feature"


def test_workflow_manager_slug_from_runner_id():
    """R(Right): _slug_from_runner_id — runner-{id[:8]} 생성"""
    slug = WorkflowManager._slug_from_runner_id("abcdef1234567890")
    assert slug == "runner-abcdef12"


# ── Phase T1: 신규 함수 TC ─────────────────────────────────────────────────────

class TestNormalizePlanKey:
    """_normalize_plan_key 동치 검증"""

    def test_none_returns_sentinel(self):
        assert WorkflowManager._normalize_plan_key(None) == "__ALL_PLANS__"

    def test_empty_string_returns_sentinel(self):
        assert WorkflowManager._normalize_plan_key("") == "__ALL_PLANS__"

    def test_whitespace_returns_sentinel(self):
        assert WorkflowManager._normalize_plan_key("   ") == "__ALL_PLANS__"

    def test_ALL_returns_sentinel(self):
        assert WorkflowManager._normalize_plan_key("ALL") == "__ALL_PLANS__"

    def test_dunder_ALL_PLANS_returns_sentinel(self):
        assert WorkflowManager._normalize_plan_key("__ALL_PLANS__") == "__ALL_PLANS__"

    def test_backslash_normalized_to_slash(self):
        result = WorkflowManager._normalize_plan_key("docs\\plan\\test.md")
        assert result == "docs/plan/test.md"

    def test_forward_slash_preserved(self):
        result = WorkflowManager._normalize_plan_key("docs/plan/test.md")
        assert result == "docs/plan/test.md"

    def test_absolute_path_windows_normalized(self):
        result = WorkflowManager._normalize_plan_key("D:\\work\\project\\docs\\plan\\test.md")
        assert result == "D:/work/project/docs/plan/test.md"

    def test_regular_path_not_sentinel(self):
        result = WorkflowManager._normalize_plan_key("docs/plan/2026-04-06_my-plan.md")
        assert result != "__ALL_PLANS__"


class TestCountStartedRunsUntil:
    """count_started_runs_until: started_at IS NOT NULL AND started_at <= target 기준 집계"""

    def test_count_zero_for_empty_db(self, wf_manager):
        """B(Boundary): 빈 DB → 0"""
        result = wf_manager.count_started_runs_until("docs/plan/test.md", "2099-01-01T00:00:00")
        assert result == 0

    def test_count_includes_started_runs(self, wf_manager):
        """R(Right): started_at이 있는 레코드만 집계"""
        id1 = wf_manager.create("slug-r1", "docs/plan/test.md")
        id2 = wf_manager.create("slug-r2", "docs/plan/test.md")
        id3 = wf_manager.create("slug-r3", "docs/plan/test.md")  # not started

        wf_manager.update_status(id1, "running", runner_id="r1")
        wf_manager.update_status(id2, "running", runner_id="r2")
        # id3 remains planned (no started_at)

        plan_key = "docs/plan/test.md"
        count = wf_manager.count_started_runs_until(plan_key, "2099-01-01T00:00:00")
        assert count == 2

    def test_different_plan_not_included(self, wf_manager):
        """R(Right): 다른 plan_key 레코드는 집계에서 제외"""
        id1 = wf_manager.create("slug-a", "docs/plan/plan-a.md")
        id2 = wf_manager.create("slug-b", "docs/plan/plan-b.md")
        wf_manager.update_status(id1, "running", runner_id="r1")
        wf_manager.update_status(id2, "running", runner_id="r2")

        count_a = wf_manager.count_started_runs_until("docs/plan/plan-a.md", "2099-01-01T00:00:00")
        count_b = wf_manager.count_started_runs_until("docs/plan/plan-b.md", "2099-01-01T00:00:00")
        assert count_a == 1
        assert count_b == 1

    def test_sentinel_group_counts_null_and_ALL(self, wf_manager):
        """R(Right): __ALL_PLANS__ sentinel — plan_file=None/ALL 레코드 집계"""
        id1 = wf_manager.create("slug-all1", None)
        id2 = wf_manager.create("slug-all2", "ALL")
        id3 = wf_manager.create("slug-specific", "docs/plan/specific.md")
        wf_manager.update_status(id1, "running", runner_id="r1")
        wf_manager.update_status(id2, "running", runner_id="r2")
        wf_manager.update_status(id3, "running", runner_id="r3")

        count = wf_manager.count_started_runs_until("__ALL_PLANS__", "2099-01-01T00:00:00")
        # id1 (None) + id2 (ALL) = 2, id3 (specific) 미포함
        assert count == 2


class TestMarkRunningWithExecutionCount:
    """mark_running_with_execution_count: running 전이 + started_at + 순번 원자 처리"""

    def test_first_run_returns_count_1(self, wf_manager):
        """R(Right): plan 첫 실행 → execution_count=1"""
        wf_id = wf_manager.create("slug-first", "docs/plan/test.md")
        started_at, count = wf_manager.mark_running_with_execution_count(
            wf_id, "runner-1", "plan/test", "/worktrees/test", "python"
        )
        assert count == 1
        assert started_at is not None

    def test_second_run_returns_count_2(self, wf_manager):
        """R(Right): 같은 plan 2번째 실행 → execution_count=2"""
        id1 = wf_manager.create("slug-run1", "docs/plan/test.md")
        id2 = wf_manager.create("slug-run2", "docs/plan/test.md")

        _, count1 = wf_manager.mark_running_with_execution_count(
            id1, "runner-1", "plan/test", "/wt/1", "python"
        )
        _, count2 = wf_manager.mark_running_with_execution_count(
            id2, "runner-2", "plan/test", "/wt/2", "python"
        )
        assert count1 == 1
        assert count2 == 2

    def test_nonexistent_id_raises_value_error(self, wf_manager):
        """E(Error): 없는 id → ValueError"""
        with pytest.raises(ValueError, match="workflow not found"):
            wf_manager.mark_running_with_execution_count(
                99999, "runner-x", "plan/test", "/wt/x", "python"
            )

    def test_status_becomes_running(self, wf_manager):
        """R(Right): mark_running 후 status='running'으로 변경됨"""
        wf_id = wf_manager.create("slug-status", "docs/plan/test.md")
        wf_manager.mark_running_with_execution_count(
            wf_id, "runner-1", "plan/test", "/wt/1", "python"
        )
        row = wf_manager.get_by_slug("slug-status")
        assert row["status"] == "running"
        assert row["runner_id"] == "runner-1"
        assert row["started_at"] is not None
