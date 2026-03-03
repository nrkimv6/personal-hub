"""resolve_project_dir + process_merge fallback TC — RIGHT-BICEP 기반

resolve_project_dir() 헬퍼 함수 검증 및
process_merge()의 project_dir fallback 체인 검증.
"""

import json
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# plan-runner 모듈을 직접 import 가능하도록 sys.path에 추가
_PLAN_RUNNER_DIR = Path(r"D:\work\project\service\wtools\common\tools\plan-runner")
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

from core.merge import resolve_project_dir, MergeRequest, MergeOrchestrator


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def projects_json(tmp_path):
    """임시 projects.json 파일 생성 및 경로 반환"""
    data = {
        "projects": [
            {"name": "monitor-page", "path": r"D:\work\project\tools\monitor-page"},
            {"name": "wtools", "path": r"D:\work\project\service\wtools"},
        ]
    }
    p = tmp_path / "projects.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# RIGHT: 정상 동작 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_found(projects_json):
    """R: 존재하는 프로젝트명 → 올바른 Path 반환"""
    result = resolve_project_dir("monitor-page", projects_json)
    assert result == Path(r"D:\work\project\tools\monitor-page")


# ---------------------------------------------------------------------------
# BOUNDARY: 경계값 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_not_found(projects_json):
    """B: 존재하지 않는 프로젝트명 → None 반환"""
    result = resolve_project_dir("nonexistent", projects_json)
    assert result is None


# ---------------------------------------------------------------------------
# EDGE: 예외 상황 — resolve_project_dir
# ---------------------------------------------------------------------------


def test_resolve_project_dir_file_missing():
    """E: projects.json 파일 미존재 → None 반환 (예외 미전파)"""
    result = resolve_project_dir("monitor-page", Path("/nonexistent/path.json"))
    assert result is None


def test_resolve_project_dir_invalid_json(tmp_path):
    """E: 잘못된 JSON → None 반환 (예외 미전파)"""
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{", encoding="utf-8")
    result = resolve_project_dir("monitor-page", bad)
    assert result is None


# ---------------------------------------------------------------------------
# RIGHT: process_merge project_dir fallback 체인
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_merge_project_dir_from_worktree_path(projects_json):
    """R: worktree_path 지정 → wt.parent.parent가 project_dir"""
    worktree = r"D:\work\project\tools\monitor-page\.worktrees\test"
    request = MergeRequest(
        runner_id="test-runner",
        branch="impl/test",
        worktree_path=worktree,
        plan_file="",
        project="monitor-page",
        timestamp="2026-03-03T00:00:00",
    )

    mock_redis = Mock()
    mock_config = Mock()
    mock_config.merge_queue_key = "plan-runner:merge-queue"
    mock_config.projects_json_path = projects_json
    mock_config.merge_lock_timeout_seconds = 300

    orch = MergeOrchestrator.__new__(MergeOrchestrator)
    orch.redis = mock_redis
    orch.config = mock_config
    orch._shutdown = False

    captured_project_dir = {}

    def fake_merge_branch(branch, project_dir):
        captured_project_dir["value"] = project_dir
        result = Mock()
        result.success = True
        result.conflict = False
        result.message = ""
        return result

    with (
        patch("core.merge.merge_branch", side_effect=fake_merge_branch),
        patch("core.merge.MergeOrchestrator._set_status"),
        patch("core.merge.MergeOrchestrator._cleanup_worktree"),
        patch("core.merge.MergeOrchestrator._publish_result"),
        patch("core.merge.pre_merge_gate", return_value=(True, "ok"), create=True),
        patch("core.merge.release_merge_lock", create=True),
        patch("core.merge.run_http_tests", return_value=Mock(passed=True, output="", exit_code=0)),
    ):
        try:
            await orch.process_merge(request)
        except Exception:
            pass

    assert captured_project_dir.get("value") == Path(worktree).parent.parent


@pytest.mark.asyncio
async def test_process_merge_project_dir_from_project_field(projects_json):
    """R: worktree_path="" + project 지정 → projects.json lookup 결과가 project_dir"""
    request = MergeRequest(
        runner_id="test-runner",
        branch="impl/test",
        worktree_path="",
        plan_file="",
        project="monitor-page",
        timestamp="2026-03-03T00:00:00",
    )

    mock_redis = Mock()
    mock_config = Mock()
    mock_config.merge_queue_key = "plan-runner:merge-queue"
    mock_config.projects_json_path = projects_json
    mock_config.merge_lock_timeout_seconds = 300

    orch = MergeOrchestrator.__new__(MergeOrchestrator)
    orch.redis = mock_redis
    orch.config = mock_config
    orch._shutdown = False

    captured_project_dir = {}
    resolve_calls = []

    original_resolve = resolve_project_dir

    def fake_resolve(name, pj):
        resolve_calls.append((name, pj))
        return original_resolve(name, pj)

    def fake_merge_branch(branch, project_dir):
        captured_project_dir["value"] = project_dir
        result = Mock()
        result.success = True
        result.conflict = False
        result.message = ""
        return result

    with (
        patch("core.merge.resolve_project_dir", side_effect=fake_resolve),
        patch("core.merge.merge_branch", side_effect=fake_merge_branch),
        patch("core.merge.MergeOrchestrator._set_status"),
        patch("core.merge.MergeOrchestrator._cleanup_worktree"),
        patch("core.merge.MergeOrchestrator._publish_result"),
        patch("core.merge.pre_merge_gate", return_value=(True, "ok"), create=True),
        patch("core.merge.release_merge_lock", create=True),
        patch("core.merge.run_http_tests", return_value=Mock(passed=True, output="", exit_code=0)),
    ):
        try:
            await orch.process_merge(request)
        except Exception:
            pass

    # resolve_project_dir 호출 확인
    assert len(resolve_calls) >= 1
    assert resolve_calls[0][0] == "monitor-page"
    # project_dir이 projects.json에서 resolved된 경로
    assert captured_project_dir.get("value") == Path(r"D:\work\project\tools\monitor-page")


@pytest.mark.asyncio
async def test_process_merge_project_dir_fallback(tmp_path):
    """B: worktree_path="" + project="" → config.base_dir fallback"""
    request = MergeRequest(
        runner_id="test-runner",
        branch="impl/test",
        worktree_path="",
        plan_file="",
        project="",
        timestamp="2026-03-03T00:00:00",
    )

    fallback_dir = Path("/fallback")
    mock_redis = Mock()
    mock_config = Mock()
    mock_config.merge_queue_key = "plan-runner:merge-queue"
    mock_config.projects_json_path = tmp_path / "nonexistent.json"
    mock_config.base_dir = fallback_dir
    mock_config.merge_lock_timeout_seconds = 300

    orch = MergeOrchestrator.__new__(MergeOrchestrator)
    orch.redis = mock_redis
    orch.config = mock_config
    orch._shutdown = False

    captured_project_dir = {}

    def fake_merge_branch(branch, project_dir):
        captured_project_dir["value"] = project_dir
        result = Mock()
        result.success = True
        result.conflict = False
        result.message = ""
        return result

    # pipeline 모듈을 sys.modules에 주입하여 from .pipeline import ... 가 작동하도록
    fake_pipeline = types.ModuleType("core.pipeline")
    fake_pipeline.pre_merge_gate = Mock(return_value=(True, "ok"))
    fake_pipeline.release_merge_lock = Mock()
    fake_pipeline.auto_commit_stage = Mock()

    with (
        patch.dict(sys.modules, {"core.pipeline": fake_pipeline}),
        patch("core.merge.merge_branch", side_effect=fake_merge_branch),
        patch("core.merge.MergeOrchestrator._set_status"),
        patch("core.merge.MergeOrchestrator._cleanup_worktree"),
        patch("core.merge.MergeOrchestrator._publish_result"),
        patch("core.merge.run_http_tests", return_value=Mock(passed=True, output="", exit_code=0)),
    ):
        try:
            await orch.process_merge(request)
        except Exception:
            pass

    assert captured_project_dir.get("value") == fallback_dir
