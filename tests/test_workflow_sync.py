"""
WorkflowManager.sync_from_worktrees() 단위 테스트

Phase 1 TC:
  - test_sync_import_error: E — WorktreeManager import 실패 → 0 반환
  - test_sync_list_worktrees_error: E — list_worktrees 예외 → 0 반환
  - test_sync_no_runner_id: B — runner_id 없는 worktree → 스킵
  - test_sync_skips_existing: B — 이미 존재하는 runner_id → 스킵
  - test_sync_creates_new_workflows: R — 새 worktree 3개 → 3개 생성
  - test_sync_slug_dedup: B — slug 중복 → suffix 추가
  - test_sync_create_failure_continues: E — 일부 create 실패 → 나머지 계속
"""
import pytest
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from workflow_manager import WorkflowManager


@pytest.fixture
def wf_manager(tmp_path):
    """임시 SQLite DB + workflows 테이블 초기화"""
    db_path = tmp_path / "test_workflow.db"
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


def _make_wt(runner_id="runner-abc123", plan_file=None, branch="plan/test", path="/tmp/wt"):
    return {
        "runner_id": runner_id,
        "plan_file": plan_file,
        "branch": branch,
        "path": path,
    }


def test_sync_import_error(wf_manager, tmp_path):
    """E(Error): WorktreeManager import 실패 → 0 반환"""
    with patch.dict("sys.modules", {"worktree_manager": None}):
        result = wf_manager.sync_from_worktrees(tmp_path)
    assert result == 0


def test_sync_list_worktrees_error(wf_manager, tmp_path):
    """E(Error): list_worktrees 예외 → 0 반환"""
    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.side_effect = Exception("disk I/O error")
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)
    assert result == 0


def test_sync_no_runner_id(wf_manager, tmp_path):
    """B(Boundary): runner_id 없는 worktree → 스킵, 0 반환"""
    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.return_value = [
        {"runner_id": "", "plan_file": None, "branch": "", "path": "/tmp/wt"},
        {"plan_file": None, "branch": "", "path": "/tmp/wt2"},  # runner_id 키 없음
    ]
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)
    assert result == 0


def test_sync_skips_existing(wf_manager, tmp_path):
    """B(Boundary): 이미 존재하는 runner_id → 스킵, 새로운 것만 생성"""
    # DB에 runner-exist 미리 생성
    wf_id = wf_manager.create("existing-slug", None)
    wf_manager.update_status(wf_id, "running", runner_id="runner-exist")

    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.return_value = [
        _make_wt("runner-exist"),   # 이미 있음 → 스킵
        _make_wt("runner-new123"),  # 새것 → 생성
    ]
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)

    assert result == 1
    new_wf = wf_manager.get_by_runner_id("runner-new123")
    assert new_wf is not None
    assert new_wf["status"] == "running"


def test_sync_creates_new_workflows(wf_manager, tmp_path):
    """R(Right): 새 worktree 3개 → 3개 생성, 각 status=running"""
    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.return_value = [
        _make_wt("runner-aaa", "docs/plan/2026-03-01_feat-a_todo.md", "plan/feat-a", "/tmp/wt-a"),
        _make_wt("runner-bbb", "docs/plan/2026-03-02_feat-b_todo.md", "plan/feat-b", "/tmp/wt-b"),
        _make_wt("runner-ccc", None, "plan/feat-c", "/tmp/wt-c"),
    ]
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)

    assert result == 3
    for runner_id in ("runner-aaa", "runner-bbb", "runner-ccc"):
        wf = wf_manager.get_by_runner_id(runner_id)
        assert wf is not None, f"{runner_id} not found"
        assert wf["status"] == "running"

    # plan_file 기반 slug (_todo 제거 확인)
    wf_a = wf_manager.get_by_runner_id("runner-aaa")
    assert "feat-a" in wf_a["slug"]
    assert "_todo" not in wf_a["slug"]


def test_sync_slug_dedup(wf_manager, tmp_path):
    """B(Boundary): 동일 plan_file slug 중복 → suffix 추가"""
    # 먼저 같은 slug로 레코드 생성
    wf_manager.create("2026-03-01_feat-a", "docs/plan/2026-03-01_feat-a_todo.md")

    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.return_value = [
        _make_wt("runner-zzz9", "docs/plan/2026-03-01_feat-a_todo.md"),
    ]
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)

    assert result == 1
    wf = wf_manager.get_by_runner_id("runner-zzz9")
    assert wf is not None
    # slug에 runner_id[:4] suffix 추가 확인 ("runner-zzz9"[:4] = "runn")
    assert wf["slug"] != "2026-03-01_feat-a"  # 원래 slug와 다름
    assert wf["slug"].startswith("2026-03-01_feat-a-")  # suffix 붙음


def test_sync_create_failure_continues(wf_manager, tmp_path):
    """E(Error): 일부 worktree create 실패해도 나머지 계속 처리"""
    mock_module = MagicMock()
    mock_module.WorktreeManager.list_worktrees.return_value = [
        _make_wt("runner-ok1"),
        _make_wt("runner-ok1"),  # 중복 slug → create 시 IntegrityError
        _make_wt("runner-ok2"),
    ]
    with patch.dict("sys.modules", {"worktree_manager": mock_module}):
        result = wf_manager.sync_from_worktrees(tmp_path)

    # ok1은 성공, 중복 slug는 실패, ok2는 성공 (또는 slug suffix로 성공)
    assert result >= 1
    assert wf_manager.get_by_runner_id("runner-ok2") is not None
