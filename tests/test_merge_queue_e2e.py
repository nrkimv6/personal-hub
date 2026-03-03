"""
Merge Queue Pipeline E2E 테스트

실제 파이프라인 흐름을 fakeredis + mock으로 검증:
- plan 완료 → merge queue 진입
- MergeWorkflow.run() 성공/충돌 경로
- _do_retry_merge() 전체 흐름
- SSE 로그 스트림 연동
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

# scripts 경로 추가
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis 미설치")

MERGE_QUEUE_KEY = "plan-runner:merge-queue"
RUNNER_KEY_PREFIX = "plan-runner:runners"


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def merge_workflow(redis_client):
    from merge_workflow import MergeWorkflow
    return MergeWorkflow(
        project_root=Path("D:/work/project/tools/monitor-page"),
        redis_client=redis_client,
    )


def make_merge_request(runner_id="test_r1", branch="plan/2026-03-03_test", plan_file="docs/plan/test.md"):
    return {
        "runner_id": runner_id,
        "branch": branch,
        "worktree_path": f"/tmp/wt/{runner_id}",
        "plan_file": plan_file,
        "project": "monitor-page",
        "timestamp": "2026-03-03T10:00:00",
        "status": "pending",
    }


# ══════════════════════════════════════════════
# TC-E1: plan 완료 → merge queue 진입 시뮬레이션
# ══════════════════════════════════════════════

class TestPlanCompleteToQueue:
    """plan-runner가 _publish_merge_request()에서 하는 것과 동일하게 큐잉 후 API 조회"""

    def test_e1_lpush_appears_in_queue(self, redis_client):
        """E1: Redis LPUSH 후 LRANGE로 해당 항목 존재 확인."""
        req = make_merge_request()
        redis_client.lpush(MERGE_QUEUE_KEY, json.dumps(req))

        items = redis_client.lrange(MERGE_QUEUE_KEY, 0, -1)
        assert len(items) == 1
        item = json.loads(items[0])
        assert item["runner_id"] == "test_r1"
        assert item["status"] == "pending"
        assert item["branch"] == "plan/2026-03-03_test"
        assert item["plan_file"] == "docs/plan/test.md"

    def test_e1_multiple_plans_fifo_order(self, redis_client):
        """E1: 여러 plan 완료 시 FIFO 순서로 큐잉."""
        for i in range(3):
            req = make_merge_request(runner_id=f"r{i}")
            redis_client.lpush(MERGE_QUEUE_KEY, json.dumps(req))

        # brpop은 오른쪽에서 꺼냄 → 첫 번째 lpush가 먼저 나옴 (FIFO)
        _, first = redis_client.brpop(MERGE_QUEUE_KEY, timeout=1)
        assert json.loads(first)["runner_id"] == "r0"


# ══════════════════════════════════════════════
# TC-E2: MergeWorkflow.run() 성공 경로
# ══════════════════════════════════════════════

class TestMergeWorkflowSuccess:
    """MergeWorkflow.run() 성공 시 큐 상태 변화 + merge_status 키 확인"""

    def test_e2_success_path(self, merge_workflow, redis_client):
        """E2: merge 성공 → 큐 status done, merge_status=merged."""
        runner_id = "success_r1"
        req = make_merge_request(runner_id=runner_id)
        redis_client.lpush(MERGE_QUEUE_KEY, json.dumps(req))

        # WorktreeManager.merge_to_main mock (성공)
        mock_merge_result = MagicMock()
        mock_merge_result.success = True
        mock_merge_result.conflict = False
        mock_merge_result.message = "머지 성공"

        # run_post_merge_tests mock (통과)
        mock_test_result = MagicMock()
        mock_test_result.passed = True
        mock_test_result.output = "all passed"
        mock_test_result.exit_code = 0

        with patch("worktree_manager.WorktreeManager") as mock_wm, \
             patch.object(merge_workflow, "run_post_merge_tests", return_value=mock_test_result), \
             patch("subprocess.run"):  # git add/commit mock
            mock_wm.merge_to_main.return_value = mock_merge_result
            mock_wm.remove = MagicMock()
            result = merge_workflow.run(runner_id, Path(f"/tmp/wt/{runner_id}"), Path("/tmp/worktrees"), plan_file="docs/plan/test.md")

        assert result.merged is True
        assert result.tests_passed is True

        # 큐 상태 확인
        items = redis_client.lrange(MERGE_QUEUE_KEY, 0, -1)
        if items:
            item = json.loads(items[0])
            assert item["status"] == "done"

        # merge_status Redis 키
        status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        assert status == "merged"


# ══════════════════════════════════════════════
# TC-E3: MergeWorkflow.run() 충돌 경로
# ══════════════════════════════════════════════

class TestMergeWorkflowConflict:
    """MergeWorkflow.run() 충돌 시 상태 확인"""

    def test_e3_conflict_path(self, merge_workflow, redis_client):
        """E3: merge 충돌 → merged=False, merge_status=conflict."""
        runner_id = "conflict_r1"
        req = make_merge_request(runner_id=runner_id)
        redis_client.lpush(MERGE_QUEUE_KEY, json.dumps(req))

        mock_merge_result = MagicMock()
        mock_merge_result.success = False
        mock_merge_result.conflict = True
        mock_merge_result.message = "CONFLICT (content): merge conflict in app/main.py"

        with patch("worktree_manager.WorktreeManager") as mock_wm, \
             patch("subprocess.run"):
            mock_wm.merge_to_main.return_value = mock_merge_result
            result = merge_workflow.run(runner_id, Path(f"/tmp/wt/{runner_id}"), Path("/tmp/worktrees"))

        assert result.merged is False
        assert result.conflict is True

        # merge_status = conflict
        status = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
        assert status == "conflict"

        # 큐 상태 = failed
        items = redis_client.lrange(MERGE_QUEUE_KEY, 0, -1)
        if items:
            item = json.loads(items[0])
            assert item["status"] == "failed"


# ══════════════════════════════════════════════
# TC-E4: _do_retry_merge 전체 흐름
# ══════════════════════════════════════════════

class TestRetryMergeE2E:
    """_do_retry_merge() 호출 시 MergeWorkflow 실행 + 결과 기록"""

    def test_e4_retry_merge_success(self, redis_client):
        """E4: retry 성공 시 결과 키에 success=True 기록."""
        import importlib.util

        runner_id = "retry_r1"
        # worktree_path 설정
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path", "/tmp/wt/retry_r1")
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")

        # listener 모듈 로드
        cache_key = "dev_runner_command_listener"
        if cache_key in sys.modules:
            mod = sys.modules[cache_key]
        else:
            spec = importlib.util.spec_from_file_location(cache_key, SCRIPTS_DIR / "dev-runner-command-listener.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[cache_key] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass

        fn = mod._do_retry_merge

        # MergeWorkflow mock
        mock_wf_cls = MagicMock()
        mock_wf_instance = MagicMock()
        mock_wf_cls.return_value = mock_wf_instance
        mock_result = MagicMock()
        mock_result.merged = True
        mock_result.conflict = False
        mock_result.message = "성공"
        mock_wf_instance.run.return_value = mock_result

        mock_merge_workflow_mod = MagicMock()
        mock_merge_workflow_mod.MergeWorkflow = mock_wf_cls

        with patch.dict(sys.modules, {"merge_workflow": mock_merge_workflow_mod}), \
             patch.object(mod, "PROJECT_ROOT", Path("/proj")), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("/python")), \
             patch.object(mod, "WORKTREE_BASE_DIR", Path("/tmp/worktrees")):
            fn(runner_id, redis_client, "cmd_123")

        # 결과 키에서 확인
        result_key = f"plan-runner:command_results:cmd_123"
        results = redis_client.lrange(result_key, 0, -1)
        assert len(results) >= 1
        result_data = json.loads(results[0])
        assert result_data["success"] is True
        assert result_data["action"] == "retry-merge"


# ══════════════════════════════════════════════
# TC-E5: SSE 로그 스트림 — publish 확인
# ══════════════════════════════════════════════

class TestMergeLogPublish:
    """MergeWorkflow.run() 중 _publish_log() → Redis PUBSUB 발행 검증"""

    def test_e5_publish_log_during_merge(self, redis_client):
        """E5: merge 실행 중 PUBSUB 채널에 로그 메시지 발행."""
        from merge_workflow import MergeWorkflow
        wf = MergeWorkflow(
            project_root=Path("/tmp/proj"),
            redis_client=redis_client,
        )

        # _publish_log 직접 호출하여 Redis publish 확인
        # fakeredis pubsub은 제한적이므로 publish 호출만 검증
        spy_redis = MagicMock(wraps=redis_client)
        wf.redis_client = spy_redis

        wf._publish_log("runner_x", "MERGE", "머지 시작")

        spy_redis.publish.assert_called_once_with(
            "plan-runner:merge-log:runner_x",
            "[MERGE][MERGE] 머지 시작"
        )

    def test_e5_completed_signal(self, redis_client):
        """E5: __MERGE_COMPLETED__ 시그널 전송 확인."""
        from merge_workflow import MergeWorkflow
        wf = MergeWorkflow(
            project_root=Path("/tmp/proj"),
            redis_client=redis_client,
        )
        spy_redis = MagicMock(wraps=redis_client)
        wf.redis_client = spy_redis

        wf._publish_log("runner_x", "DONE", "__MERGE_COMPLETED__")

        spy_redis.publish.assert_called_once_with(
            "plan-runner:merge-log:runner_x",
            "[MERGE][DONE] __MERGE_COMPLETED__"
        )
