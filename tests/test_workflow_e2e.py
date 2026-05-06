"""
workflow 상태전이 E2E 시나리오 테스트

Phase 4 TC:
  - test_full_success_flow: R — planned→running→merge_pending→merging→merged 전 흐름
  - test_full_failure_flow: E — planned→running→merge_pending→merging→failed
  - test_merge_workflow_e2e_success: R — MergeWorkflow + WorkflowManager 연동 → merged
  - test_merge_workflow_e2e_conflict: E — MergeWorkflow + WorkflowManager 연동 → failed(conflict)

State-leak regression (Phase T1/T3):
  - test_worktree_manager_module_identity_stable: broad selection에서 worktree_manager module
    identity 오염이 없는지 검증. test_worktree_manager.py가 del sys.modules["worktree_manager"]를
    실행해도 wm 참조가 merge_workflow 내 late-import와 동일한 class를 공유해야 한다.
"""
import pytest
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import fakeredis

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from workflow_manager import WorkflowManager
from merge_workflow import MergeWorkflow, TestResult
import worktree_manager as wm
from worktree_manager import MergeResult


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test_e2e.db"
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE workflows (
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
    return p


@pytest.fixture
def wfm(db_path):
    return WorkflowManager(db_path)


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


# ─── Phase 4 TC ──────────────────────────────────────────────────────

def test_full_success_flow(wfm):
    """R(Right): planned→running→merge_pending→merging→merged 전체 상태전이"""
    # 1. planned
    wf_id = wfm.create("e2e-success", "docs/plan/2026-03-03_e2e.md")
    wf = wfm.get_by_slug("e2e-success")
    assert wf["status"] == "planned"
    assert wf["started_at"] is None

    # 2. running
    wfm.update_status(wf_id, "running", runner_id="runner-e2e001", branch="plan/e2e", worktree_path="/tmp/wt")
    wf = wfm.get_by_slug("e2e-success")
    assert wf["status"] == "running"
    assert wf["runner_id"] == "runner-e2e001"
    assert wf["started_at"] is not None

    # 3. merge_pending
    wfm.update_status(wf_id, "merge_pending")
    wf = wfm.get_by_slug("e2e-success")
    assert wf["status"] == "merge_pending"

    # 4. merging
    wfm.update_status(wf_id, "merging")
    wf = wfm.get_by_slug("e2e-success")
    assert wf["status"] == "merging"

    # 5. merged
    wfm.update_status(wf_id, "merged", commit_hash="abc123def456")
    wf = wfm.get_by_slug("e2e-success")
    assert wf["status"] == "merged"
    assert wf["commit_hash"] == "abc123def456"
    assert wf["merged_at"] is not None
    assert wf["finished_at"] is not None


def test_full_failure_flow(wfm):
    """E(Error): planned→running→merge_pending→merging→failed + error_message"""
    wf_id = wfm.create("e2e-failure", None)
    wfm.update_status(wf_id, "running", runner_id="runner-fail01")
    wfm.update_status(wf_id, "merge_pending")
    wfm.update_status(wf_id, "merging")
    wfm.update_status(wf_id, "failed", error_message="머지 충돌 발생")

    wf = wfm.get_by_slug("e2e-failure")
    assert wf["status"] == "failed"
    assert wf["error_message"] == "머지 충돌 발생"
    assert wf["finished_at"] is not None
    assert wf["merged_at"] is None  # failed → merged_at 미설정


def test_merge_workflow_e2e_success(wfm, fake_redis, tmp_path):
    """R(Right): MergeWorkflow.run() + WorkflowManager 연동 → DB에 status=merged"""
    wf_id = wfm.create("e2e-mw-success", None)
    wfm.update_status(wf_id, "running", runner_id="runner-mw001")

    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    base_dir = tmp_path / ".worktrees"
    base_dir.mkdir()

    mw = MergeWorkflow(tmp_path, fake_redis, python_path="python", workflow_manager=wfm)

    log_result = Mock()
    log_result.stdout = "deadbeef12345678\n"

    with patch("subprocess.run", return_value=log_result), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=True, conflict=False, message="ok")), \
         patch.object(wm.WorktreeManager, "remove", return_value=None):

        mw.run_post_merge_tests = Mock(return_value=TestResult(passed=True, output="ok", exit_code=0))
        result = mw.run("runner-mw001", worktree_path, base_dir)

    assert result.merged is True

    # DB에서 직접 확인
    wf = wfm.get_by_slug("e2e-mw-success")
    assert wf["status"] == "merged"
    assert wf["commit_hash"] is not None
    assert "deadbeef" in wf["commit_hash"]
    assert wf["merged_at"] is not None


def test_merge_workflow_e2e_conflict(wfm, fake_redis, tmp_path):
    """E(Error): MergeWorkflow.run() 충돌 → DB에 status=failed"""
    wf_id = wfm.create("e2e-mw-conflict", None)
    wfm.update_status(wf_id, "running", runner_id="runner-mw002")

    worktree_path = tmp_path / "worktree2"
    worktree_path.mkdir()
    base_dir = tmp_path / ".worktrees"
    base_dir.mkdir()

    mw = MergeWorkflow(tmp_path, fake_redis, python_path="python", workflow_manager=wfm)

    with patch("subprocess.run"), \
         patch.object(wm.WorktreeManager, "merge_to_main",
                      return_value=MergeResult(success=False, conflict=True, message="Merge conflict in app/main.py")):

        result = mw.run("runner-mw002", worktree_path, base_dir)

    assert result.merged is False

    wf = wfm.get_by_slug("e2e-mw-conflict")
    assert wf["status"] == "failed"
    assert "충돌" in wf["error_message"]
    assert wf["finished_at"] is not None


def test_worktree_manager_module_identity_stable():
    """R: sys.modules["worktree_manager"] identity가 안정적이어야 한다.

    broad selection 실행 시 test_worktree_manager.py가 del sys.modules["worktree_manager"]를
    실행하면 merge_workflow.py 내 `from worktree_manager import WorktreeManager`(late import)가
    tests/test_workflow_e2e.py의 wm.WorktreeManager와 다른 class를 가져와
    patch.object가 무력화된다. conftest restore_worktree_manager_module fixture가
    이를 방어함을 확인한다.
    """
    import sys
    import worktree_manager as _wm_direct

    # 1) wm(이 파일 상단 import)과 sys.modules의 module이 동일해야 한다
    assert wm is sys.modules.get("worktree_manager"), (
        "sys.modules['worktree_manager'] identity drift: "
        "broad selection 중 del sys.modules['worktree_manager']가 복원되지 않았을 수 있습니다."
    )

    # 2) WorktreeManager class 동일성 보장
    from worktree_manager import WorktreeManager as _WM_late
    assert wm.WorktreeManager is _WM_late, (
        "wm.WorktreeManager != late import WorktreeManager: "
        "patch.object(wm.WorktreeManager, ...) 가 merge_workflow.py 내 late-import에 반영되지 않습니다."
    )
