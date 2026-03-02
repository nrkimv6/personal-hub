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
    """R(Right): 3개 레코드(planned, running, merged) 생성 → list_workflows(status="running") → 1개만 반환"""
    id1 = wf_manager.create("slug-planned", None)
    id2 = wf_manager.create("slug-running", None)
    id3 = wf_manager.create("slug-merged", None)

    wf_manager.update_status(id2, "running")
    wf_manager.update_status(id3, "merged", commit_hash="abc123")

    all_wf = wf_manager.list_workflows()
    assert len(all_wf) == 3

    running_wf = wf_manager.list_workflows(status="running")
    assert len(running_wf) == 1
    assert running_wf[0]["slug"] == "slug-running"

    merged_wf = wf_manager.list_workflows(status="merged")
    assert len(merged_wf) == 1


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

    with pytest.raises(sqlite3.IntegrityError):
        wf_manager.create("duplicate", None)


def test_workflow_manager_slug_from_plan_file():
    """R(Right): _slug_from_plan_file — _todo 접미사 제거"""
    assert WorkflowManager._slug_from_plan_file("docs/plan/2026-03-03_workflow-manager_todo.md") == "2026-03-03_workflow-manager"
    assert WorkflowManager._slug_from_plan_file("2026-01-01_feature.md") == "2026-01-01_feature"


def test_workflow_manager_slug_from_runner_id():
    """R(Right): _slug_from_runner_id — runner-{id[:8]} 생성"""
    slug = WorkflowManager._slug_from_runner_id("abcdef1234567890")
    assert slug == "runner-abcdef12"
