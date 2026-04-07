"""T4 E2E: exit_code=0 + completed 시 워크트리 커밋 자동 merge 전체 흐름 검증

검증 범위:
- _stream_output(exit_code=0, exit_reason=completed, merge_requested 없음, worktree 커밋 있음)
  → _has_worktree_commits() 호출 (실제 git) → _do_inline_merge → _execute_merge_with_lock
  → merge_status 전이 (queued → merging → merged) → cleanup 호출

T3과의 차이:
- T3: _do_inline_merge 호출 여부만 확인 (mock)
- T4: _do_inline_merge 내부까지 실행 — merge_status 전이 + cleanup 호출까지 검증
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# noise 필터 stub
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False
sys.modules.setdefault("listener_noise_filter", _mock_noise)

import _dr_plan_runner as plan_runner_mod  # noqa: E402
import _dr_merge as dr_merge_mod  # noqa: E402

RUNNER_KEY_PREFIX = "plan-runner:runners"
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t.com",
}


@pytest.fixture
def real_git_repo_with_feature_branch():
    """임시 git 저장소 — main + feature 브랜치에 커밋 1개"""
    with tempfile.TemporaryDirectory() as tmpdir:
        env = _GIT_ENV
        subprocess.run(["git", "init", "-b", "main"], cwd=tmpdir, capture_output=True, env=env)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmpdir, capture_output=True, env=env)
        readme = Path(tmpdir) / "README.md"
        readme.write_text("init")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, env=env)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True, env=env)
        # feature 브랜치에 커밋 추가
        branch = "plan/auto-merge-e2e-test"
        subprocess.run(["git", "checkout", "-b", branch], cwd=tmpdir, capture_output=True, env=env)
        feature_file = Path(tmpdir) / "feature.py"
        feature_file.write_text("FEATURE = True")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, env=env)
        subprocess.run(["git", "commit", "-m", "feat: auto-merge e2e"], cwd=tmpdir, capture_output=True, env=env)
        # main으로 복귀
        subprocess.run(["git", "checkout", "main"], cwd=tmpdir, capture_output=True, env=env)
        yield tmpdir, branch


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode=0):
    proc = MagicMock()
    proc.stdout = io.StringIO("")
    proc.returncode = returncode
    proc.wait.return_value = returncode
    proc.poll.return_value = returncode
    return proc


def _make_wf_manager(runner_id="test-runner"):
    wf = {"id": 42, "runner_id": runner_id, "status": "running"}
    mgr = MagicMock()
    mgr.get_by_runner_id.return_value = wf
    return mgr, wf


class TestAutoMergeE2E:
    def test_auto_merge_on_completed_merge_status_transitions(
        self, real_git_repo_with_feature_branch, fr
    ):
        """T4 R: exit_code=0 + completed + worktree 커밋 있음
        → merge_status 전이 (queued → merging) + cleanup 호출 검증

        _execute_merge_with_lock 내 subprocess.run(plan-runner post-merge)을 mock하여
        E2E 흐름만 검증 (실제 plan_runner 바이너리 불필요).
        """
        repo_dir, branch = real_git_repo_with_feature_branch
        runner_id = "t4-auto-merge-e2e-001"

        # Redis 세팅: completed 경로 + branch 키 있음 (merge_requested 없음)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)

        merge_status_seq = []
        orig_set = fr.set

        def _track_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                merge_status_seq.append(value)
            return orig_set(key, value, *args, **kwargs)

        fr.set = _track_set

        proc = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        import merge_queue as mq

        post_merge_proc = MagicMock()
        post_merge_proc.returncode = 0  # merged 성공 경로

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
             patch("_dr_constants.PROJECT_ROOT", Path(repo_dir)), \
             patch.object(mq, "acquire_merge_turn", return_value=True), \
             patch.object(mq, "release_merge_turn"), \
             patch("subprocess.run", return_value=post_merge_proc):
            plan_runner_mod._stream_output(proc, log_handle, fr, runner_id=runner_id)

        # merge_status queued → merging 전이 확인
        assert "queued" in merge_status_seq, (
            f"merge_status=queued 전이 누락. 실제 전이: {merge_status_seq}"
        )
        assert "merging" in merge_status_seq, (
            f"merge_status=merging 전이 누락. 실제 전이: {merge_status_seq}"
        )
        assert merge_status_seq.index("queued") < merge_status_seq.index("merging"), (
            "queued → merging 순서 오류"
        )

        # cleanup은 _do_inline_merge 내부에서 호출 → mock_cleanup 호출 확인
        mock_cleanup.assert_called_once_with(runner_id, fr)

    def test_no_auto_merge_without_worktree_commits(self, fr):
        """T4 B: exit_code=0 + completed + worktree 커밋 없음 → merge 없이 cleanup만 호출"""
        runner_id = "t4-auto-merge-e2e-002"

        # branch 키 있지만 main 대비 커밋 0개인 상태 → _has_worktree_commits = False
        # 실제 git 없이 subprocess.run mock으로 커밋 0개 시뮬레이션
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "plan/empty-branch")

        proc = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        empty_git_proc = MagicMock()
        empty_git_proc.stdout = ""  # 커밋 없음
        empty_git_proc.returncode = 0

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_do_inline_merge") as mock_merge, \
             patch.object(plan_runner_mod, "_cleanup_process_state") as mock_cleanup, \
             patch("subprocess.run", return_value=empty_git_proc):
            plan_runner_mod._stream_output(proc, log_handle, fr, runner_id=runner_id)

        mock_merge.assert_not_called(), "워크트리 커밋 없음 → merge 호출 금지"
        mock_cleanup.assert_called_once_with(runner_id, fr)

    def test_merge_status_queued_before_merging(self, real_git_repo_with_feature_branch, fr):
        """T4 I: merge_status=queued가 merging보다 반드시 먼저 세팅되어야 한다 (순서 불변식)"""
        repo_dir, branch = real_git_repo_with_feature_branch
        runner_id = "t4-auto-merge-e2e-003"

        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:exit_reason", "completed")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)

        order = []
        orig_set = fr.set

        def _ordered_set(key, value, *args, **kwargs):
            if "merge_status" in key:
                order.append((key, value))
            return orig_set(key, value, *args, **kwargs)

        fr.set = _ordered_set

        proc = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager(runner_id)

        import merge_queue as mq

        post_merge_proc = MagicMock()
        post_merge_proc.returncode = 0

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "detect_merged_but_not_done", return_value=None), \
             patch.object(plan_runner_mod, "_cleanup_process_state"), \
             patch("_dr_constants.PROJECT_ROOT", Path(repo_dir)), \
             patch.object(mq, "acquire_merge_turn", return_value=True), \
             patch.object(mq, "release_merge_turn"), \
             patch("subprocess.run", return_value=post_merge_proc):
            plan_runner_mod._stream_output(proc, log_handle, fr, runner_id=runner_id)

        statuses = [v for _, v in order]
        assert statuses, "merge_status 전이 없음"
        queued_idx = next((i for i, v in enumerate(statuses) if v == "queued"), None)
        merging_idx = next((i for i, v in enumerate(statuses) if v == "merging"), None)
        assert queued_idx is not None, "queued 전이 누락"
        assert merging_idx is not None, "merging 전이 누락"
        assert queued_idx < merging_idx, f"queued({queued_idx}) > merging({merging_idx}): 순서 역전"
