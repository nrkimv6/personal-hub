"""
T4 E2E: _execute_merge_with_lock + BRPOP 큐 순서화 통합 테스트

TC-1: full flow (fakeredis) — acquire → subprocess exit_code=0 → release → merge-results push
TC-2: conflict path (fakeredis) — acquire → subprocess exit_code=3 → release → status "failed"
TC-3: queued runner gets turn (실물 Redis DB15) — A/B 동시 enqueue → A release → B 깨어남

⚠️ fakeredis는 Lua eval 미지원 — merge_queue.py의 acquire_merge_turn()이
_ENQUEUE_LUA 스크립트를 eval()로 실행하므로 `unknown command 'eval'` 오류 발생.
merge_queue 함수를 직접 호출하는 TC(TC-1, TC-2)는 반드시 mock_merge_queue_turn() 사용.
"""
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
import fakeredis

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from merge_queue import acquire_merge_turn, release_merge_turn, get_merge_queue, _RUNNER_KEY_PREFIX
from _dr_merge import _EXIT_CODE_HANDLERS

# mock_merge_queue_turn: conftest.py에 정의된 헬퍼 (pytest conftest는 직접 import 불가)
# 동일한 context manager를 인라인으로 참조
from contextlib import contextmanager
from unittest.mock import patch as _patch


@contextmanager
def mock_merge_queue_turn(repo_id: str):
    """conftest.mock_merge_queue_turn와 동일 — 이 파일에서 직접 사용하기 위한 참조 복사본.
    conftest.py가 원본이며, 정의를 변경할 경우 conftest.py를 먼저 수정할 것.

    ⚠️ fakeredis는 Lua eval 미지원 — acquire_merge_turn을 직접 호출하는 TC에서 필수.
    """
    with _patch("merge_queue.acquire_merge_turn", return_value=True), \
         _patch("merge_queue.release_merge_turn", return_value=True), \
         _patch("merge_queue._get_repo_id", return_value=repo_id):
        yield

REPO_ID = "test-e2e-brpop"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fr():
    """fakeredis 동기 클라이언트 (decode_responses=True)"""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def rr():
    """실물 Redis DB15 클라이언트. 테스트 종료 시 관련 키 정리."""
    import redis
    client = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    yield client
    keys = (
        client.keys("plan-runner:merge-queue:test-e2e-*")
        + client.keys("plan-runner:merge-turn:*")
        + client.keys("plan-runner:merge-results")
    )
    if keys:
        client.delete(*keys)
    client.close()


# ---------------------------------------------------------------------------
# TC-1: full flow — exit_code=0 → merge-results "done"
# ---------------------------------------------------------------------------

class TestMergeQueueE2EFullFlow:
    """TC-1: fakeredis 기반 _execute_merge_with_lock 정상 흐름"""

    def test_merge_queue_e2e_full_flow(self, fr):
        """acquire → subprocess exit_code=0 → release → merge-results status="done"

        fakeredis는 단일 스레드 동기 클라이언트이므로 LINDEX 0 == me → 즉시 True.
        subprocess.run을 mock하여 exit_code=0 반환.
        merge-results에 {"status": "done", "success": true} 항목이 push됐는지 확인.
        """
        runner_id = "e2e-runner-full"
        branch = "plan/2026-03-30_test"
        plan_file = "docs/plan/2026-03-30_test.md"

        # per-runner 키 사전 설정
        fr.set(f"{_RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
        fr.set(f"{_RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        # _handle_merged: merge_status = "merged", success=True 반환
        merge_success_result = {
            "success": True,
            "message": "merge 성공",
            "merge_status": "merged",
            "action": "inline-merge",
        }

        handler_name = _EXIT_CODE_HANDLERS[0].__name__
        with mock_merge_queue_turn(REPO_ID), \
             patch("subprocess.run", return_value=mock_proc), \
             patch(f"_dr_merge.{handler_name}", return_value=merge_success_result) as mock_handler, \
             patch("_dr_merge._pub_and_log"):
            from _dr_merge import _execute_merge_with_lock
            result = _execute_merge_with_lock(runner_id, fr)

        # acquire → release 흐름 검증: 큐가 비어있어야 함
        queue = get_merge_queue(fr, repo_id=REPO_ID)
        assert queue == [], f"release 후 큐가 비어 있어야 함, 실제: {queue}"

        # merge-results push 검증
        raw = fr.lindex("plan-runner:merge-results", 0)
        assert raw is not None, "merge-results에 항목이 push됐어야 함"
        pushed = json.loads(raw)
        assert pushed["runner_id"] == runner_id
        assert pushed["status"] == "done", f"status 불일치: {pushed['status']}"
        assert pushed["success"] is True


# ---------------------------------------------------------------------------
# TC-2: conflict path — exit_code=3 → merge-results status="failed"
# ---------------------------------------------------------------------------

class TestMergeQueueE2EConflictPath:
    """TC-2: fakeredis 기반 conflict 경로"""

    def test_merge_queue_e2e_conflict_path(self, fr):
        """acquire → subprocess exit_code=3 → release → merge-results status="failed"

        exit_code=3은 conflict 핸들러(_handle_conflict)를 호출한다.
        최종적으로 merge-results에 success=False, status="failed" 항목이 push되어야 한다.
        """
        runner_id = "e2e-runner-conflict"
        branch = "plan/2026-03-30_conflict"
        plan_file = "docs/plan/2026-03-30_conflict.md"

        fr.set(f"{_RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
        fr.set(f"{_RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)

        mock_proc = MagicMock()
        mock_proc.returncode = 3

        conflict_result = {
            "success": False,
            "message": "conflict 발생",
            "merge_status": "conflict",
            "action": "inline-merge",
        }

        handler_name = _EXIT_CODE_HANDLERS[3].__name__
        with mock_merge_queue_turn(REPO_ID), \
             patch("subprocess.run", return_value=mock_proc), \
             patch(f"_dr_merge.{handler_name}", return_value=conflict_result), \
             patch("_dr_merge._pub_and_log"):
            from _dr_merge import _execute_merge_with_lock
            result = _execute_merge_with_lock(runner_id, fr)

        # release 검증: 큐 비어있어야 함
        queue = get_merge_queue(fr, repo_id=REPO_ID)
        assert queue == [], f"release 후 큐가 비어 있어야 함, 실제: {queue}"

        # merge-results 검증: status="failed"
        raw = fr.lindex("plan-runner:merge-results", 0)
        assert raw is not None, "merge-results에 항목이 push됐어야 함"
        pushed = json.loads(raw)
        assert pushed["runner_id"] == runner_id
        assert pushed["status"] == "failed", f"status 불일치: {pushed['status']}"
        assert pushed["success"] is False


# ---------------------------------------------------------------------------
# TC-3: queued runner gets turn — 실물 Redis DB15 + threading
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestMergeQueueE2EQueuedRunnerGetsTurn:
    """TC-3: 실물 Redis DB15 — A/B 동시 enqueue → A release → B 깨어남"""

    def test_merge_queue_e2e_queued_runner_gets_turn(self, rr):
        """A/B 동시 enqueue → A merge 완료 release → B BRPOP signal 수신 후 turn 획득

        스레드별 독립 Redis 클라이언트를 사용한다.
        A가 먼저 enqueue되어 즉시 turn 획득 → B는 BRPOP 대기.
        A가 release 하면 B가 깨어나 turn 을 획득해야 한다.
        """
        import redis as redis_lib

        runner_a = "e2e-brpop-runner-a"
        runner_b = "e2e-brpop-runner-b"
        results = {}

        def _make_client():
            return redis_lib.Redis(
                host="localhost", port=6379, db=15, decode_responses=True
            )

        def run_a():
            r = _make_client()
            try:
                acquired = acquire_merge_turn(r, runner_a, repo_id=REPO_ID, timeout=30, queue_ttl=60)
                results["a_acquired"] = acquired
                if acquired:
                    # A가 turn 획득 후 잠시 점유 → B가 BRPOP 대기할 시간 확보
                    time.sleep(0.5)
                    released = release_merge_turn(r, runner_a, repo_id=REPO_ID)
                    results["a_released"] = released
            finally:
                r.close()

        def run_b():
            r = _make_client()
            try:
                # A보다 약간 늦게 enqueue하여 A가 front가 되도록 보장
                time.sleep(0.1)
                acquired = acquire_merge_turn(r, runner_b, repo_id=REPO_ID, timeout=30, queue_ttl=60)
                results["b_acquired"] = acquired
                if acquired:
                    released = release_merge_turn(r, runner_b, repo_id=REPO_ID)
                    results["b_released"] = released
            finally:
                r.close()

        thread_a = threading.Thread(target=run_a, name="runner-a")
        thread_b = threading.Thread(target=run_b, name="runner-b")

        thread_a.start()
        thread_b.start()

        thread_a.join(timeout=35)
        thread_b.join(timeout=35)

        assert not thread_a.is_alive(), "thread_a 타임아웃"
        assert not thread_b.is_alive(), "thread_b 타임아웃"

        assert results.get("a_acquired") is True, "A가 turn을 획득해야 함"
        assert results.get("a_released") is True, "A가 turn을 release해야 함"
        assert results.get("b_acquired") is True, "B가 A release 후 turn을 획득해야 함"
        assert results.get("b_released") is True, "B가 turn을 release해야 함"

        # 최종 큐 비어있어야 함
        final_queue = get_merge_queue(rr, repo_id=REPO_ID)
        assert final_queue == [], f"모든 release 후 큐가 비어 있어야 함, 실제: {final_queue}"


# ---------------------------------------------------------------------------
# T1 TCs: mock_merge_queue_turn 헬퍼 + _EXIT_CODE_HANDLERS 일관성 검증
# ---------------------------------------------------------------------------

class TestMockHelperAndHandlerConsistency:
    """mock_merge_queue_turn 헬퍼 동작 + _EXIT_CODE_HANDLERS 함수명 일관성 검증"""

    def test_mock_merge_queue_turn_helper_right(self):
        """R: mock_merge_queue_turn 내에서 acquire_merge_turn/release_merge_turn/_get_repo_id mock 정상 동작"""
        import merge_queue as mq

        test_repo = "test-repo-helper"
        with mock_merge_queue_turn(test_repo):
            acquired = mq.acquire_merge_turn(None, "runner", repo_id=test_repo)
            released = mq.release_merge_turn(None, "runner", repo_id=test_repo)
            repo = mq._get_repo_id("/any/path")

        assert acquired is True, "acquire_merge_turn이 True를 반환해야 함"
        assert released is True, "release_merge_turn이 True를 반환해야 함"
        assert repo == test_repo, f"_get_repo_id가 '{test_repo}'를 반환해야 함"

    def test_exit_code_handler_name_consistency_right(self):
        """R: _EXIT_CODE_HANDLERS의 각 handler가 _dr_merge 모듈에 실제 존재하는지 확인

        함수명 변경/삭제 시 즉시 실패하여 TC-1/TC-2의 동적 patch 불일치를 탐지.
        """
        import _dr_merge

        for exit_code, handler in _EXIT_CODE_HANDLERS.items():
            assert hasattr(_dr_merge, handler.__name__), (
                f"_EXIT_CODE_HANDLERS[{exit_code}]={handler.__name__!r}가 "
                f"_dr_merge 모듈에 존재하지 않음 — TC의 동적 patch가 깨질 수 있음"
            )
