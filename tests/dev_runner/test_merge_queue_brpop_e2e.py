"""
T4 E2E: _execute_merge_with_lock + BRPOP 큐 순서화 통합 테스트

TC-1: full flow (fakeredis) — acquire → subprocess exit_code=0 → release → merge-results push
TC-2: conflict path (fakeredis) — acquire → subprocess exit_code=3 → release → status "failed"
TC-3: queued runner gets turn (실물 Redis DB15) — A/B 동시 enqueue → A release → B 깨어남
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

        with patch("subprocess.run", return_value=mock_proc), \
             patch("_dr_merge._handle_merge_success", return_value=merge_success_result) as mock_handler, \
             patch("_dr_merge._pub_and_log"), \
             patch("merge_queue.acquire_merge_turn", return_value=True), \
             patch("merge_queue.release_merge_turn", return_value=True), \
             patch("merge_queue._get_repo_id", return_value=REPO_ID):
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

        with patch("subprocess.run", return_value=mock_proc), \
             patch("_dr_merge._handle_conflict", return_value=conflict_result), \
             patch("_dr_merge._pub_and_log"), \
             patch("merge_queue.acquire_merge_turn", return_value=True), \
             patch("merge_queue.release_merge_turn", return_value=True), \
             patch("merge_queue._get_repo_id", return_value=REPO_ID):
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
