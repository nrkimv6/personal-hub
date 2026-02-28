"""
MergeQueue 관련 단위 테스트

대상 함수:
- _enqueue_merge_request() (dev-runner-command-listener.py)
- MergeWorkflow._update_queue_status() (merge_workflow.py)
- MergeWorkflow._publish_log() (merge_workflow.py)
- LogService.stream_merge_log() (log_service.py)
- _cleanup_process_state() 내 queued 조건 (dev-runner-command-listener.py)

RIGHT-BICEP:
- Right: 정상 경로 결과 검증
- Boundary: 경계값 (빈 큐, 없는 runner_id, None 값)
- Error: 예외 상황 (Redis 다운, 잘못된 JSON)
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, call
from datetime import datetime

import importlib.util

# scripts 경로 추가
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# app 경로 추가
APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))


def _load_listener_module():
    """파일명에 하이픈이 있어 importlib으로 로드 (한 번만 로드, 이후 캐시 반환)"""
    cache_key = "dev_runner_command_listener"
    if cache_key in sys.modules:
        return sys.modules[cache_key]
    spec = importlib.util.spec_from_file_location(
        cache_key,
        SCRIPTS_DIR / "dev-runner-command-listener.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Redis/환경 의존 초기화를 막기 위해 sys.modules에 먼저 등록
    sys.modules[cache_key] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # 모듈 최상위 Redis 연결 등 실패해도 함수 정의는 완료됨
        pass
    return mod


# ──────────────────────────────────────────────
# 헬퍼: mock Redis 클라이언트 생성
# ──────────────────────────────────────────────

def make_redis(*, get_map=None, lrange_result=None):
    """간단한 동기 Redis mock 생성"""
    r = MagicMock()
    get_map = get_map or {}

    def _get(key):
        return get_map.get(key)

    r.get.side_effect = _get
    r.lrange.return_value = lrange_result or []
    return r


# ══════════════════════════════════════════════
# 1. _enqueue_merge_request() 테스트
# ══════════════════════════════════════════════

class TestEnqueueMergeRequest:
    """_enqueue_merge_request() 단위 테스트"""

    def _import_fn(self):
        mod = _load_listener_module()
        return mod._enqueue_merge_request

    def test_enqueue_merge_request_right(self):
        """R: exit=0 + worktree_path 존재 시 올바른 JSON 항목이 큐에 추가된다."""
        fn = self._import_fn()
        runner_id = "abc123"
        r = make_redis(get_map={
            "plan-runner:runners:abc123:worktree_path": "/tmp/wt/abc123",
            "plan-runner:runners:abc123:plan_file": "docs/plan/feat.md",
            "plan-runner:runners:abc123:branch": "runner/abc123",
        })

        fn(runner_id, r)

        assert r.lpush.call_count == 1
        call_args = r.lpush.call_args
        queue_name, raw = call_args[0]
        assert queue_name == "plan-runner:merge-queue"
        item = json.loads(raw)
        assert item["runner_id"] == runner_id
        assert item["branch"] == "runner/abc123"
        assert item["worktree_path"] == "/tmp/wt/abc123"
        assert item["plan_file"] == "docs/plan/feat.md"
        assert item["status"] == "pending"
        assert "timestamp" in item
        assert "project" in item

    def test_enqueue_merge_request_sets_queued(self):
        """R: merge_status Redis 키가 "queued"로 SET된다."""
        fn = self._import_fn()
        runner_id = "abc123"
        r = make_redis(get_map={
            "plan-runner:runners:abc123:worktree_path": "/tmp/wt/abc123",
            "plan-runner:runners:abc123:plan_file": "docs/plan/feat.md",
        })

        fn(runner_id, r)

        r.set.assert_called_once_with(
            "plan-runner:runners:abc123:merge_status", "queued"
        )

    def test_enqueue_merge_request_boundary_no_worktree(self):
        """B: worktree_path가 None이어도 lpush는 여전히 호출된다 (None 값으로 저장)."""
        fn = self._import_fn()
        runner_id = "no_wt"
        r = make_redis(get_map={
            "plan-runner:runners:no_wt:worktree_path": None,
            "plan-runner:runners:no_wt:plan_file": "docs/plan/feat.md",
        })

        # worktree_path가 None이어도 예외 없이 실행되어야 한다
        fn(runner_id, r)
        # lpush는 호출됨 (None 값 포함)
        assert r.lpush.call_count == 1
        raw = r.lpush.call_args[0][1]
        item = json.loads(raw)
        assert item["worktree_path"] is None

    def test_enqueue_merge_request_boundary_no_branch(self):
        """B: branch 키 없을 때 "runner/{runner_id}" 기본값이 사용된다."""
        fn = self._import_fn()
        runner_id = "nb_runner"
        r = make_redis(get_map={
            "plan-runner:runners:nb_runner:worktree_path": "/tmp/wt",
            "plan-runner:runners:nb_runner:plan_file": "docs/plan/feat.md",
            # branch 키 없음 → None → fallback
        })

        fn(runner_id, r)

        raw = r.lpush.call_args[0][1]
        item = json.loads(raw)
        assert item["branch"] == f"runner/{runner_id}"

    def test_enqueue_merge_request_boundary_plan_file_all(self):
        """B: plan_file == "ALL"일 때 None으로 치환된다."""
        fn = self._import_fn()
        runner_id = "all_runner"
        r = make_redis(get_map={
            "plan-runner:runners:all_runner:worktree_path": "/tmp/wt",
            "plan-runner:runners:all_runner:plan_file": "ALL",
        })

        fn(runner_id, r)

        raw = r.lpush.call_args[0][1]
        item = json.loads(raw)
        assert item["plan_file"] is None

    def test_enqueue_merge_request_error_redis_down(self):
        """E: Redis lpush 실패 시 예외 전파 없이 종료된다."""
        fn = self._import_fn()
        runner_id = "err_runner"
        r = MagicMock()
        r.get.return_value = "/tmp/wt"
        r.lpush.side_effect = Exception("Redis connection refused")

        # 예외가 밖으로 전파되면 안 된다
        fn(runner_id, r)  # should not raise


# ══════════════════════════════════════════════
# 2. MergeWorkflow._update_queue_status() 테스트
# ══════════════════════════════════════════════

class TestUpdateQueueStatus:
    """MergeWorkflow._update_queue_status() 단위 테스트"""

    def _make_wf(self, redis_mock):
        from merge_workflow import MergeWorkflow  # noqa: PLC0415
        wf = MergeWorkflow(project_root=Path("/tmp/proj"), redis_client=redis_mock)
        return wf

    def _make_queue_items(self, items):
        """리스트를 JSON 인코딩된 bytes 리스트로 변환"""
        return [json.dumps(i).encode() for i in items]

    def test_update_queue_status_right(self):
        """R: 큐 내 항목 status 필드가 "pending" → "merging"으로 정상 갱신된다."""
        runner_id = "r1"
        items = [
            {"runner_id": "r1", "status": "pending"},
            {"runner_id": "r2", "status": "pending"},
        ]
        r = MagicMock()
        r.lrange.return_value = self._make_queue_items(items)
        wf = self._make_wf(r)

        wf._update_queue_status(runner_id, "merging")

        # index 0이 r1이므로 lset(queue, 0, ...) 호출
        r.lset.assert_called_once()
        call_args = r.lset.call_args[0]
        assert call_args[0] == "plan-runner:merge-queue"
        assert call_args[1] == 0
        updated = json.loads(call_args[2])
        assert updated["status"] == "merging"
        assert updated["runner_id"] == "r1"

    def test_update_queue_status_boundary_empty_queue(self):
        """B: 빈 큐에서 호출 시 에러 없이 반환된다."""
        r = MagicMock()
        r.lrange.return_value = []
        wf = self._make_wf(r)

        wf._update_queue_status("any_id", "merging")  # should not raise
        r.lset.assert_not_called()

    def test_update_queue_status_boundary_runner_not_in_queue(self):
        """B: 해당 runner_id가 큐에 없을 때 lset 호출 없이 무시된다."""
        r = MagicMock()
        r.lrange.return_value = self._make_queue_items([
            {"runner_id": "other_id", "status": "pending"}
        ])
        wf = self._make_wf(r)

        wf._update_queue_status("ghost_id", "merging")
        r.lset.assert_not_called()

    def test_update_queue_status_boundary_multiple_items(self):
        """B: 큐에 여러 항목 있을 때 정확한 runner_id만 갱신된다."""
        r = MagicMock()
        items = [
            {"runner_id": "r1", "status": "pending"},
            {"runner_id": "r2", "status": "pending"},
            {"runner_id": "r3", "status": "pending"},
        ]
        r.lrange.return_value = self._make_queue_items(items)
        wf = self._make_wf(r)

        wf._update_queue_status("r2", "merging")

        r.lset.assert_called_once()
        idx = r.lset.call_args[0][1]
        assert idx == 1  # r2는 index 1
        updated = json.loads(r.lset.call_args[0][2])
        assert updated["runner_id"] == "r2"
        assert updated["status"] == "merging"

    def test_update_queue_status_invalid_json_skipped(self):
        """E: 큐 내 JSON 파싱 실패 항목은 조용히 스킵된다."""
        r = MagicMock()
        r.lrange.return_value = [b"not valid json", json.dumps({"runner_id": "r1", "status": "pending"}).encode()]
        wf = self._make_wf(r)

        wf._update_queue_status("r1", "merging")  # should not raise
        r.lset.assert_called_once()
        idx = r.lset.call_args[0][1]
        assert idx == 1


# ══════════════════════════════════════════════
# 3. MergeWorkflow._publish_log() 테스트
# ══════════════════════════════════════════════

class TestPublishLog:
    """MergeWorkflow._publish_log() 단위 테스트"""

    def _make_wf(self, redis_mock):
        from merge_workflow import MergeWorkflow  # noqa: PLC0415
        return MergeWorkflow(project_root=Path("/tmp/proj"), redis_client=redis_mock)

    def test_publish_log_right(self):
        """R: 올바른 채널명과 형식으로 Redis publish가 호출된다."""
        r = MagicMock()
        wf = self._make_wf(r)

        wf._publish_log("runner_x", "COMMIT", "변경사항 커밋 중...")

        r.publish.assert_called_once_with(
            "plan-runner:merge-log:runner_x",
            "[MERGE][COMMIT] 변경사항 커밋 중..."
        )

    def test_publish_log_error_redis_down(self):
        """E: Redis publish 실패 시 예외가 전파되지 않는다."""
        r = MagicMock()
        r.publish.side_effect = Exception("connection refused")
        wf = self._make_wf(r)

        wf._publish_log("runner_x", "MERGE", "머지 중...")  # should not raise


# ══════════════════════════════════════════════
# 4. stream_merge_log() SSE 엔드포인트 테스트
# ══════════════════════════════════════════════

class TestStreamMergeLog:
    """LogService.stream_merge_log() 단위 테스트"""

    def _make_service(self, async_redis_mock):
        # LogService 경로 추가
        from app.modules.dev_runner.services.log_service import LogService  # noqa: PLC0415
        svc = LogService.__new__(LogService)
        svc.async_redis = async_redis_mock
        return svc

    @pytest.mark.asyncio
    async def test_stream_merge_log_right(self):
        """R: Redis publish → SSE 스트림으로 올바른 data 형식 전달 확인."""
        import asyncio
        ar = MagicMock()
        pubsub = AsyncMock()

        # subscribe 성공, 3번 메시지 후 종료
        messages = [
            {"type": "message", "data": "[MERGE][COMMIT] 커밋 완료"},
            {"type": "message", "data": "[MERGE][MERGE] 머지 성공"},
            {"type": "message", "data": "__MERGE_COMPLETED__"},
        ]
        idx = {"i": 0}

        async def _get_message(**kwargs):
            if idx["i"] < len(messages):
                msg = messages[idx["i"]]
                idx["i"] += 1
                return msg
            return None

        pubsub.get_message.side_effect = _get_message
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        ar.pubsub.return_value = pubsub

        svc = self._make_service(ar)
        results = []
        async for chunk in svc.stream_merge_log("runner_x"):
            results.append(chunk)
            if "event: completed" in chunk:
                break

        # 첫 청크는 connected 이벤트
        assert results[0] == "event: connected\ndata: ok\n\n"
        # 일반 메시지들은 data: 형식
        assert any("[MERGE][COMMIT] 커밋 완료" in r for r in results)
        # 완료 이벤트
        assert any("event: completed" in r for r in results)

    @pytest.mark.asyncio
    async def test_stream_merge_log_boundary_completed(self):
        """B: __MERGE_COMPLETED__ 수신 시 event: completed 전송 후 스트림 종료."""
        ar = MagicMock()
        pubsub = AsyncMock()
        pubsub.get_message = AsyncMock(return_value={
            "type": "message",
            "data": "__MERGE_COMPLETED__"
        })
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        ar.pubsub.return_value = pubsub

        svc = self._make_service(ar)
        results = []
        async for chunk in svc.stream_merge_log("r999"):
            results.append(chunk)
            # completed 이벤트 수신 시 break (generator가 return하므로 자동 종료)

        assert any("event: completed" in r for r in results)
        # unsubscribe 호출 확인
        pubsub.unsubscribe.assert_called_once()


# ══════════════════════════════════════════════
# 5. _cleanup_process_state() queued 조건 테스트
# ══════════════════════════════════════════════

class TestCleanupProcessState:
    """_cleanup_process_state() 내 queued 조건 단위 테스트"""

    def _import_fn(self):
        mod = _load_listener_module()
        return mod._cleanup_process_state

    def _make_redis_with_status(self, merge_status):
        r = MagicMock()

        def _get(key):
            if key.endswith(":merge_status"):
                return merge_status
            return None

        r.get.side_effect = _get
        return r

    def test_cleanup_skips_worktree_when_queued(self):
        """R: merge_status == "queued"일 때 WorktreeManager.remove() 호출하지 않는다."""
        fn = self._import_fn()
        r = self._make_redis_with_status("queued")

        mod = _load_listener_module()
        with patch.object(mod, "WorktreeManager") as mock_wm, \
             patch.object(mod, "_running_processes", {}), \
             patch.object(mod, "_running_log_files", {}), \
             patch.object(mod, "_stream_threads", {}), \
             patch.object(mod, "WORKTREE_BASE_DIR", Path("/tmp/worktrees")):
            fn("runner_queued", r)
            mock_wm.remove.assert_not_called()

    def test_cleanup_skips_worktree_when_pending_merge(self):
        """R: merge_status == "pending_merge"일 때도 WorktreeManager.remove() 호출하지 않는다."""
        fn = self._import_fn()
        r = self._make_redis_with_status("pending_merge")
        mod = _load_listener_module()
        with patch.object(mod, "WorktreeManager") as mock_wm, \
             patch.object(mod, "_running_processes", {}), \
             patch.object(mod, "_running_log_files", {}), \
             patch.object(mod, "_stream_threads", {}), \
             patch.object(mod, "WORKTREE_BASE_DIR", Path("/tmp/worktrees")):
            fn("runner_pm", r)
            mock_wm.remove.assert_not_called()

    def test_cleanup_removes_worktree_when_no_status(self):
        """R: merge_status가 None(없음)일 때 WorktreeManager.remove() 정상 호출된다."""
        fn = self._import_fn()
        r = self._make_redis_with_status(None)
        r.get.side_effect = lambda key: None  # 모든 키 None
        mod = _load_listener_module()
        with patch.object(mod, "WorktreeManager") as mock_wm, \
             patch.object(mod, "_running_processes", {}), \
             patch.object(mod, "_running_log_files", {}), \
             patch.object(mod, "_stream_threads", {}), \
             patch.object(mod, "WORKTREE_BASE_DIR", Path("/tmp/worktrees")):
            fn("runner_none", r)
            mock_wm.remove.assert_called_once()


# ══════════════════════════════════════════════
# 6. retry_merge() plan_file 전달 TC
# ══════════════════════════════════════════════

class TestRetryMergePlanFile:
    """retry_merge() — plan_file Redis 조회 후 wf.run() 전달 검증"""

    def _import_fn(self):
        mod = _load_listener_module()
        return mod.retry_merge

    def _run_with_mock_wf(self, fn, runner_id, r, expected_plan_file):
        """retry_merge()의 로컬 import MergeWorkflow를 sys.modules 패치로 mock."""
        mock_wf_cls = MagicMock()
        mock_wf_instance = MagicMock()
        mock_wf_cls.return_value = mock_wf_instance
        mock_result = MagicMock()
        mock_result.merged = True
        mock_result.conflict = False
        mock_result.message = "성공"
        mock_wf_instance.run.return_value = mock_result

        mod = _load_listener_module()
        mock_merge_workflow_mod = MagicMock()
        mock_merge_workflow_mod.MergeWorkflow = mock_wf_cls

        with patch.dict(sys.modules, {"merge_workflow": mock_merge_workflow_mod}), \
             patch.object(mod, "PROJECT_ROOT", Path("/proj")), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("/python")), \
             patch.object(mod, "WORKTREE_BASE_DIR", Path("/tmp/worktrees")):
            fn(runner_id, r)

        mock_wf_instance.run.assert_called_once()
        call_kwargs = mock_wf_instance.run.call_args
        passed = call_kwargs.kwargs.get("plan_file", call_kwargs.args[3] if len(call_kwargs.args) >= 4 else "NOT_FOUND")
        return passed

    def test_retry_merge_right_passes_plan_file(self):
        """R: Redis에 plan_file="2026-02-27_foo.md" 설정 → wf.run(plan_file="2026-02-27_foo.md") 전달."""
        fn = self._import_fn()
        runner_id = "rid_foo"
        r = make_redis(get_map={
            f"plan-runner:runners:{runner_id}:worktree_path": "/tmp/wt/rid_foo",
            f"plan-runner:runners:{runner_id}:plan_file": "2026-02-27_foo.md",
        })
        passed = self._run_with_mock_wf(fn, runner_id, r, "2026-02-27_foo.md")
        assert passed == "2026-02-27_foo.md"

    def test_retry_merge_boundary_plan_file_all(self):
        """B: Redis plan_file="ALL" → wf.run(plan_file=None) 전달 (parallel 모드 placeholder)."""
        fn = self._import_fn()
        runner_id = "rid_all"
        r = make_redis(get_map={
            f"plan-runner:runners:{runner_id}:worktree_path": "/tmp/wt/rid_all",
            f"plan-runner:runners:{runner_id}:plan_file": "ALL",
        })
        passed = self._run_with_mock_wf(fn, runner_id, r, None)
        assert passed is None

    def test_retry_merge_boundary_no_plan_file_key(self):
        """B: Redis에 plan_file 키 없음(None 반환) → wf.run(plan_file=None) 전달."""
        fn = self._import_fn()
        runner_id = "rid_nokey"
        r = make_redis(get_map={
            f"plan-runner:runners:{runner_id}:worktree_path": "/tmp/wt/rid_nokey",
            # plan_file 키 없음
        })
        passed = self._run_with_mock_wf(fn, runner_id, r, None)
        assert passed is None
