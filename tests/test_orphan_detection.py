"""
고아 워크플로우/plan 탐지 단위 테스트

Phase T1 TC:
  - test_detect_orphan_workflow_running_R: running workflow가 active_runners에 없으면 failed 처리
  - test_detect_orphan_workflow_merge_pending_R: merge_pending도 동일하게 failed 처리
  - test_detect_orphan_workflow_active_skipped_B: active_runners에 있으면 스킵
  - test_detect_orphan_workflow_no_manager_B: _wf_manager=None → return 0
  - test_cleanup_process_state_merge_pending_R: merge_pending 상태도 failed 처리
  - test_detect_orphan_plans_no_match_R: plan 구현중인데 DB에 running 없으면 경고
  - test_detect_orphan_plans_healthy_B: 정상이면 경고 없음
"""
import importlib.util
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import fakeredis


# ─── 모듈 로드 ─────────────────────────────────
_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    # 워크트리 또는 원본에서 스크립트 로드
    wt_path = Path(__file__).resolve().parents[1] / "scripts" / "dev-runner-command-listener.py"
    script_path = wt_path if wt_path.exists() else Path("D:/work/project/tools/monitor-page/scripts/dev-runner-command-listener.py")
    if not script_path.exists():
        pytest.skip(f"Listener script not found: {script_path}")
    spec = importlib.util.spec_from_file_location("dev_runner_orphan", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dev_runner_orphan"] = mod
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener():
    return _get_listener()


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def mock_wf_manager():
    mgr = Mock()
    mgr.list_workflows = Mock(return_value=[])
    mgr.update_status = Mock()
    mgr.get_by_runner_id = Mock(return_value=None)
    return mgr


# ─── _detect_orphan_workflows ─────────────────────────────────

def test_detect_orphan_workflow_running_R(listener, fr, mock_wf_manager):
    """running workflow가 active_runners에 없으면 failed 처리"""
    mock_wf_manager.list_workflows = Mock(side_effect=lambda status=None: [
        {"id": 1, "runner_id": "abc12345", "slug": "test-plan", "status": "running"}
    ] if status == "running" else [])

    with patch.object(listener, "_wf_manager", mock_wf_manager):
        result = listener._detect_orphan_workflows(fr)

    assert result == 1
    mock_wf_manager.update_status.assert_called_once_with(
        1, "failed", error_message="orphan: listener 재시작 시 active_runners에 없음"
    )


def test_detect_orphan_workflow_merge_pending_R(listener, fr, mock_wf_manager):
    """merge_pending workflow도 failed 처리"""
    mock_wf_manager.list_workflows = Mock(side_effect=lambda status=None: [
        {"id": 2, "runner_id": "def67890", "slug": "merge-plan", "status": "merge_pending"}
    ] if status == "merge_pending" else [])

    with patch.object(listener, "_wf_manager", mock_wf_manager):
        result = listener._detect_orphan_workflows(fr)

    assert result == 1
    mock_wf_manager.update_status.assert_called_once_with(
        2, "failed", error_message="orphan: listener 재시작 시 active_runners에 없음"
    )


def test_detect_orphan_workflow_active_skipped_B(listener, fr, mock_wf_manager):
    """active_runners에 있으면 스킵"""
    fr.sadd("plan-runner:active_runners", "abc12345")
    mock_wf_manager.list_workflows = Mock(side_effect=lambda status=None: [
        {"id": 1, "runner_id": "abc12345", "slug": "test-plan", "status": "running"}
    ] if status == "running" else [])

    with patch.object(listener, "_wf_manager", mock_wf_manager):
        result = listener._detect_orphan_workflows(fr)

    assert result == 0
    mock_wf_manager.update_status.assert_not_called()


def test_detect_orphan_workflow_no_manager_B(listener, fr):
    """_wf_manager=None → return 0, 예외 없음"""
    with patch.object(listener, "_wf_manager", None):
        result = listener._detect_orphan_workflows(fr)
    assert result == 0


def test_cleanup_process_state_merge_pending_R(listener, fr, mock_wf_manager):
    """_cleanup_process_state: merge_pending 상태도 failed 처리"""
    mock_wf_manager.get_by_runner_id.return_value = {"id": 3, "status": "merge_pending", "runner_id": "r1"}

    with patch.object(listener, "_wf_manager", mock_wf_manager), \
         patch.object(listener, "_running_processes", {}), \
         patch.object(listener, "_running_log_files", {}), \
         patch.object(listener, "_stream_threads", {}), \
         patch.object(listener, "WorktreeManager") as mock_wt:
        mock_wt.remove = Mock()
        listener._cleanup_process_state("r1", fr, "test")

    mock_wf_manager.update_status.assert_called_once_with(
        3, "failed", error_message="Cleanup: test"
    )


# ─── _detect_orphan_plans ─────────────────────────────────

def test_detect_orphan_plans_no_match_R(listener, fr, mock_wf_manager, tmp_path):
    """plan 파일이 구현중인데 DB에 running 레코드 없으면 경고"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-01-01_test.md").write_text("> 상태: 구현중\n# Test\n", encoding="utf-8")

    mock_wf_manager.list_workflows = Mock(return_value=[])

    with patch.object(listener, "_wf_manager", mock_wf_manager), \
         patch.object(listener, "PROJECT_ROOT", tmp_path):
        result = listener._detect_orphan_plans(fr)

    assert result == 1


def test_detect_orphan_plans_healthy_B(listener, fr, mock_wf_manager, tmp_path):
    """정상: plan 구현중 + DB running + active_runners에 있음 → 경고 없음"""
    plan_dir = tmp_path / "docs" / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-01-01_test.md").write_text("> 상태: 구현중\n# Test\n", encoding="utf-8")

    fr.sadd("plan-runner:active_runners", "r1")
    mock_wf_manager.list_workflows = Mock(return_value=[
        {"id": 1, "runner_id": "r1", "plan_file": "2026-01-01_test.md", "status": "running"}
    ])

    with patch.object(listener, "_wf_manager", mock_wf_manager), \
         patch.object(listener, "PROJECT_ROOT", tmp_path):
        result = listener._detect_orphan_plans(fr)

    assert result == 0
