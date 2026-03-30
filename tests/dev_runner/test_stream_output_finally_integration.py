"""T3: _stream_output() finally 블록 머지/cleanup 로그 pub/sub 통합 검증

근본 원인 재현:
  수정 전: finally 블록에서 logger.info()만 사용 → Redis channel에 publish 안 됨
  수정 후: _pub_and_log() 사용 → Redis channel에 publish됨

실제 fakeredis pub/sub 연결로 수신 여부 검증 (mock 최소화).
"""
import importlib.util
import io
import sys
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import fakeredis


# ========== 모듈 로드 ==========

def _load_plan_runner_mod():
    worktree = Path("D:/work/project/tools/monitor-page/.worktrees/impl-fix-logviewer-merge-cleanup-logs/scripts")
    if not worktree.exists():
        pytest.skip(f"worktree not found: {worktree}")
    if str(worktree) not in sys.path:
        sys.path.insert(0, str(worktree))
    script_path = worktree / "_dr_plan_runner.py"
    spec = importlib.util.spec_from_file_location("_dr_plan_runner_integ", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plan_runner_mod():
    return _load_plan_runner_mod()


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture
def fr(fake_server):
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


@pytest.fixture
def fr_sub(fake_server):
    """pub/sub 전용 별도 클라이언트"""
    return fakeredis.FakeRedis(server=fake_server, decode_responses=True)


def _make_process(returncode=0):
    p = MagicMock()
    p.stdout = io.StringIO("")  # readline() 지원
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


class TestStreamOutputFinallyMergeLogsInPubSub:
    """T3: 실제 fakeredis pub/sub 연결로 finally 블록의 머지/cleanup 로그 수신 검증"""

    def test_stream_output_finally_merge_logs_in_pubsub(self, plan_runner_mod, fr, fr_sub):
        """T3: finally 블록 _pub_and_log() 호출 → pub/sub 구독자가 로그 수신

        근본 원인 재현:
        - 수정 전이라면 `published` 리스트가 비어 있어야 함
        - 수정 후이므로 merge 판정 로그가 수신돼야 함
        """
        runner_id = "t3-finally-pubsub-001"
        log_channel = f"{LOG_CHANNEL_PREFIX}:{runner_id}"

        # pub/sub 구독 시작
        pubsub = fr_sub.pubsub()
        pubsub.subscribe(log_channel)
        # 첫 subscribe 메시지 소비
        pubsub.get_message(timeout=0.1)

        received = []

        def subscriber_thread():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    received.append(msg["data"])

        t = threading.Thread(target=subscriber_thread, daemon=True)
        t.start()

        process = _make_process(returncode=0)
        log_handle = io.StringIO()
        wf_mgr, _ = _make_wf_manager()

        with patch.object(plan_runner_mod, "get_wf_manager", return_value=wf_mgr), \
             patch.object(plan_runner_mod, "get_running_log_files", return_value={}), \
             patch.object(plan_runner_mod, "_do_inline_merge"), \
             patch.object(plan_runner_mod, "_cleanup_process_state"):
            plan_runner_mod._stream_output(process, log_handle, fr, runner_id=runner_id)

        t.join(timeout=2.5)

        # 수신된 메시지 중 merge 판정 로그 확인
        merge_decision_msgs = [m for m in received if "merge 분기 판정" in m]
        assert merge_decision_msgs, (
            f"pub/sub 구독자가 merge 판정 로그를 수신하지 못함. received={received}"
        )

        # CLEANUP 태그 확인
        cleanup_tagged = [m for m in received if "[CLEANUP]" in m]
        assert cleanup_tagged, f"[CLEANUP] 태그 로그가 수신되지 않음. received={received}"
