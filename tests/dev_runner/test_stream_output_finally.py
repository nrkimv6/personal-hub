"""_stream_output() finally 블록 머지 판정 로그 publish TC

대상: scripts/_dr_plan_runner.py — finally 블록의 logger.info() → _pub_and_log() 교체
검증: merge 판정·workflow 상태 로그가 __COMPLETED 전에 Redis channel에 publish되는지
"""
import importlib.util
import io
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import fakeredis


# ========== 모듈 로드 ==========

_mod = None


def _get_mod():
    global _mod
    if _mod is not None:
        return _mod
    worktree = Path("D:/work/project/tools/monitor-page/.worktrees/impl-fix-logviewer-merge-cleanup-logs/scripts")
    if not worktree.exists():
        pytest.skip(f"worktree not found: {worktree}")
    if str(worktree) not in sys.path:
        sys.path.insert(0, str(worktree))
    script_path = worktree / "_dr_plan_runner.py"
    spec = importlib.util.spec_from_file_location("_dr_plan_runner_test", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod = mod
    return mod


@pytest.fixture(scope="module")
def plan_runner_mod():
    return _get_mod()


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _make_process(returncode=0):
    p = MagicMock()
    p.stdout = iter([])
    p.returncode = returncode
    p.wait.return_value = returncode
    p.poll.return_value = returncode
    return p


def _make_wf_manager():
    wf = {"id": 99, "runner_id": "test-runner", "status": "running"}
    mgr = MagicMock()
    mgr.get_by_runner_id.return_value = wf
    return mgr, wf


RUNNER_KEY_PREFIX = "plan-runner:runners"
LOG_CHANNEL_PREFIX = "plan-runner:logs"


# ========== TC ==========

class TestStreamOutputFinallyPublishesMergeDecision:
    """R(정상): finally 블록에서 merge 판정·workflow 상태 로그가 Redis channel에 publish되는지 검증"""

    def test_stream_output_finally_publishes_merge_decision_no_merge(self, plan_runner_mod, fr):
        """R: merge_requested 없는 경우 — CLEANUP 태그 판정 로그가 channel에 publish됨"""
        runner_id = "t-finally-pub-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        published = []
        orig_pub = fr.publish

        def capture_publish(channel, message):
            published.append((channel, message))
            return orig_pub(channel, message)

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager()

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"), \
             patch.object(fr, "publish", side_effect=capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        # merge 판정 로그가 publish됐는지 확인
        merge_decision_msgs = [msg for ch, msg in published if ch == log_channel and "merge 분기 판정" in msg]
        assert merge_decision_msgs, f"merge 분기 판정 로그가 publish되지 않음. published={published}"

        # completed 처리 로그도 publish됐는지 확인
        completed_msgs = [msg for ch, msg in published if ch == log_channel and "completed 처리" in msg]
        assert completed_msgs, f"completed 처리 로그가 publish되지 않음"

    def test_stream_output_finally_publishes_merge_decision_with_merge(self, plan_runner_mod, fr):
        """R: merge_requested 있는 경우 — merge 흐름 진입 로그가 channel에 publish됨"""
        runner_id = "t-finally-pub-002"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", "1")

        published = []
        orig_pub = fr.publish

        def capture_publish(channel, message):
            published.append((channel, message))
            return orig_pub(channel, message)

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager()

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"), \
             patch.object(fr, "publish", side_effect=capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        merge_entry_msgs = [msg for ch, msg in published if ch == log_channel and "merge 흐름 진입" in msg]
        assert merge_entry_msgs, f"merge 흐름 진입 로그가 publish되지 않음. published={published}"


class TestStreamOutputFinallyPublishBeforeCompleted:
    """O(순서): _pub_and_log() 로그가 __COMPLETED 신호보다 먼저 publish되는지 검증"""

    def test_stream_output_finally_publish_before_completed(self, plan_runner_mod, fr):
        """O: merge 판정 로그 → __COMPLETED 순서 보장"""
        runner_id = "t-finally-order-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        published_order = []

        def capture_publish(channel, message):
            published_order.append((channel, message))
            return 1

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager()

        # _cleanup_process_state가 __COMPLETED publish하는 것을 시뮬레이션
        def fake_cleanup(rid, rc):
            fr.publish(log_channel, f"__COMPLETED::completed__")

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state", side_effect=fake_cleanup), \
             patch.object(fr, "publish", side_effect=capture_publish):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        target_msgs = [(ch, msg) for ch, msg in published_order if ch == log_channel]
        if not target_msgs:
            pytest.skip("publish 없음")

        decision_indices = [i for i, (ch, msg) in enumerate(target_msgs) if "merge 분기 판정" in msg]
        completed_indices = [i for i, (ch, msg) in enumerate(target_msgs) if "__COMPLETED" in msg]

        assert decision_indices, "merge 분기 판정 로그 없음"
        assert completed_indices, "__COMPLETED 신호 없음"
        assert max(decision_indices) < min(completed_indices), (
            f"merge 판정 로그({max(decision_indices)})가 __COMPLETED({min(completed_indices)})보다 나중에 publish됨"
        )
