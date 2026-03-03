"""
MergeQueue 관련 단위 테스트

대상 함수:
- _do_retry_merge() (dev-runner-command-listener.py)
- MergeWorkflow._update_queue_status() (merge_workflow.py)
- MergeWorkflow._publish_log() (merge_workflow.py)
- LogService.stream_merge_log() (log_service.py)
- _cleanup_process_state() 내 queued 조건 (dev-runner-command-listener.py)
- _launch_plan_runner_process() branch 저장 (dev-runner-command-listener.py)

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


## TestEnqueueMergeRequest 삭제됨 — 큐잉은 plan-runner CLI(_publish_merge_request)가 담당
## 이 프로젝트(monitor-page)의 TC 대상이 아님 (wtools 프로젝트 TC로 이동)


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
    """_do_retry_merge() — plan_file Redis 조회 후 wf.run() 전달 검증

    retry_merge(command: Dict, redis)는 백그라운드 스레드로 _do_retry_merge()를 호출.
    여기서는 _do_retry_merge()를 직접 테스트하여 plan_file 전달을 검증한다.
    """

    def _import_fn(self):
        mod = _load_listener_module()
        return mod._do_retry_merge

    def _run_with_mock_wf(self, fn, runner_id, r):
        """_do_retry_merge()의 로컬 import MergeWorkflow를 sys.modules 패치로 mock."""
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
            fn(runner_id, r, "test_cmd_id")

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
        passed = self._run_with_mock_wf(fn, runner_id, r)
        assert passed == "2026-02-27_foo.md"

    def test_retry_merge_boundary_plan_file_all(self):
        """B: Redis plan_file="ALL" → wf.run(plan_file=None) 전달 (parallel 모드 placeholder)."""
        fn = self._import_fn()
        runner_id = "rid_all"
        r = make_redis(get_map={
            f"plan-runner:runners:{runner_id}:worktree_path": "/tmp/wt/rid_all",
            f"plan-runner:runners:{runner_id}:plan_file": "ALL",
        })
        passed = self._run_with_mock_wf(fn, runner_id, r)
        assert passed is None

    def test_retry_merge_boundary_no_plan_file_key(self):
        """B: Redis에 plan_file 키 없음(None 반환) → wf.run(plan_file=None) 전달."""
        fn = self._import_fn()
        runner_id = "rid_nokey"
        r = make_redis(get_map={
            f"plan-runner:runners:{runner_id}:worktree_path": "/tmp/wt/rid_nokey",
            # plan_file 키 없음
        })
        passed = self._run_with_mock_wf(fn, runner_id, r)
        assert passed is None


# ══════════════════════════════════════════════
# 7. _launch_plan_runner_process() branch 저장 + _enqueue_merge_request() branch 사용 TC
# ══════════════════════════════════════════════

class TestLaunchPlanRunnerBranchSave:
    """_launch_plan_runner_process() — branch 키를 Redis에 저장하는지 검증 (Phase 4 수정)"""

    def test_launch_plan_runner_saves_branch_to_redis_with_plan_file(self):
        """T4-37: branch="plan/2026-02-27_foo" 전달 시 Redis에 ...:{runner_id}:branch 저장."""
        mod = _load_listener_module()
        fn = mod._launch_plan_runner_process

        runner_id = "launch_rid_1"
        r = MagicMock()
        r.set = MagicMock()

        mock_process = MagicMock()
        mock_process.pid = 12345

        with patch("subprocess.Popen", return_value=mock_process), \
             patch("threading.Thread"), \
             patch.object(mod, "RUNNER_KEY_PREFIX", "plan-runner:runners"), \
             patch.object(mod, "ACTIVE_RUNNERS_KEY", "plan-runner:active"), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("/python")), \
             patch.object(mod, "PLAN_RUNNER_MODULE_PATH", Path("/plan-runner")), \
             patch.object(mod, "LOG_DIR", Path("/tmp/logs")), \
             patch("builtins.open", MagicMock()):
            fn(
                command={},
                redis_client=r,
                runner_id=runner_id,
                worktree_path=Path("/tmp/wt/launch_rid_1"),
                plan_file="2026-02-27_foo.md",
                engine="claude",
                branch="plan/2026-02-27_foo",
            )

        set_calls = {call[0][0]: call[0][1] for call in r.set.call_args_list if len(call[0]) >= 2}
        branch_key = f"plan-runner:runners:{runner_id}:branch"
        assert branch_key in set_calls, f"branch 키 미저장. 저장된 키: {list(set_calls.keys())}"
        assert set_calls[branch_key] == "plan/2026-02-27_foo"

    def test_launch_plan_runner_saves_branch_runner_fallback(self):
        """T4-38: branch="" 전달(parallel 모드) 시 Redis에 runner/{runner_id} 저장."""
        mod = _load_listener_module()
        fn = mod._launch_plan_runner_process

        runner_id = "launch_rid_2"
        r = MagicMock()
        r.set = MagicMock()

        mock_process = MagicMock()
        mock_process.pid = 99999

        with patch("subprocess.Popen", return_value=mock_process), \
             patch("threading.Thread"), \
             patch.object(mod, "RUNNER_KEY_PREFIX", "plan-runner:runners"), \
             patch.object(mod, "ACTIVE_RUNNERS_KEY", "plan-runner:active"), \
             patch.object(mod, "PLAN_RUNNER_PYTHON", Path("/python")), \
             patch.object(mod, "PLAN_RUNNER_MODULE_PATH", Path("/plan-runner")), \
             patch.object(mod, "LOG_DIR", Path("/tmp/logs")), \
             patch("builtins.open", MagicMock()):
            fn(
                command={"parallel": True},
                redis_client=r,
                runner_id=runner_id,
                worktree_path=Path("/tmp/wt/launch_rid_2"),
                plan_file=None,
                engine="claude",
                branch="",
            )

        set_calls = {call[0][0]: call[0][1] for call in r.set.call_args_list if len(call[0]) >= 2}
        branch_key = f"plan-runner:runners:{runner_id}:branch"
        assert branch_key in set_calls, f"branch 키 미저장"
        assert set_calls[branch_key] == f"runner/{runner_id}"


## TestEnqueueMergeRequestBranchFromRedis 삭제됨 — _enqueue_merge_request()는 listener에서 삭제됨
## 큐잉은 plan-runner CLI(_publish_merge_request)가 담당, wtools 프로젝트 TC 대상
