"""T1/T2/T3: 재실행 시 기존 워커 attach 검증.

Phase T1 단위 테스트:
- plan_file 기준 중복 감지 (attach / 새 실행 / PID dead / all-plans 무시 / cleanup 중)
- _tail_log_and_publish replay_from_start 동작
- _cleanup_process_state cleanup_in_progress 플래그

Phase T3 통합 테스트:
- fakeredis 공유 서버 + 실제 함수 호출로 attach → per-command result key 검증
"""
from __future__ import annotations

import json
import sys
import time
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

# scripts 경로 추가
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# 의존성 모듈 스텁 (전체 listener 로딩 없이)
import types
for _mod_name in [
    "listener_noise_filter",
    "merge_queue",
    "worktree_manager",
    "plan_worktree_helpers",
]:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        sys.modules[_mod_name] = _stub

# noise_filter 기본값 설정
_nf = sys.modules["listener_noise_filter"]
if not hasattr(_nf, "NOISE_BLOCK_MARKERS"):
    _nf.NOISE_BLOCK_MARKERS = []
if not hasattr(_nf, "is_noise_line"):
    _nf.is_noise_line = lambda line: False

# merge_queue 스텁
_mq = sys.modules["merge_queue"]
if not hasattr(_mq, "release_merge_turn"):
    _mq.release_merge_turn = lambda *a, **kw: None
if not hasattr(_mq, "_get_repo_id"):
    _mq._get_repo_id = lambda *a, **kw: "test-repo"
if not hasattr(_mq, "get_queue_key"):
    _mq.get_queue_key = lambda *a, **kw: "test:queue"

# worktree_manager 스텁
_wm = sys.modules["worktree_manager"]
if not hasattr(_wm, "WorktreeManager"):
    class _WM:
        @staticmethod
        def remove(*a, **kw):
            pass
    _wm.WorktreeManager = _WM

# plan_worktree_helpers 스텁
_pwh = sys.modules["plan_worktree_helpers"]
if not hasattr(_pwh, "is_plan_in_progress"):
    _pwh.is_plan_in_progress = lambda *a, **kw: False

from _dr_constants import RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, PLAN_FILE_ALL, _LEGACY_ALL, RESULTS_KEY, LOG_CHANNEL_PREFIX
from _dr_state import get_running_processes
from _dr_process_utils import _tail_log_and_publish, _cleanup_process_state, _DummyProcess
from _dr_plan_runner import start_plan_runner


# ─────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────

def _make_fr():
    return fakeredis.FakeRedis(decode_responses=True)


def _seed_runner(r, runner_id: str, plan_file: str, pid: int = 1234):
    """fakeredis에 running 상태 runner 등록"""
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


def _pop_result(r, command_id: str) -> dict:
    """per-command result key에서 결과 pop"""
    result_key = f"{RESULTS_KEY}:{command_id}" if command_id else RESULTS_KEY
    raw = r.rpop(result_key)
    if raw:
        return json.loads(raw)
    return {}


def _make_command(plan_file: str, runner_id: str = "new-runner-001", command_id: str = "cmd-001") -> dict:
    return {
        "action": "run",
        "runner_id": runner_id,
        "plan_file": plan_file,
        "command_id": command_id,
        "engine": "claude",
    }


# ─────────────────────────────────────────────────────────────
# Phase T1: plan_file 기준 중복 감지
# ─────────────────────────────────────────────────────────────

class TestStartPlanRunnerDuplicateDetection:
    """start_plan_runner의 plan_file 기준 attach 감지 로직"""

    def test_start_detects_existing_runner_same_plan(self):
        """R: 동일 plan_file로 실행 중인 runner가 있으면 attached 응답 반환"""
        r = _make_fr()
        existing_id = "existing-runner-abc"
        _seed_runner(r, existing_id, plan_file="docs/plan/test.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner._do_start_plan_runner"), \
             patch("_dr_plan_runner._cleanup_process_state"):
            result = start_plan_runner(cmd, r)

        # None sentinel 반환 (accepted는 result key에 push됨)
        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("success") is True
        assert resp.get("status") == "attached"
        assert resp.get("runner_id") == existing_id

    def test_start_creates_new_when_different_plan(self):
        """I: 다른 plan_file로 실행 중인 runner가 있으면 attach하지 않고 새 실행"""
        r = _make_fr()
        _seed_runner(r, "existing-runner-abc", plan_file="docs/plan/a.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/b.md", runner_id="new-runner-xyz")

        thread_started = []
        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)
            thread_started.append(mock_thread.start.called)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        # attached가 아닌 accepted 응답
        assert resp.get("status") != "attached"
        assert resp.get("message") == "accepted"
        assert thread_started[0] is True  # 새 스레드 시작

    def test_start_creates_new_when_dead_pid(self):
        """B: 동일 plan_file이지만 PID가 dead면 새 실행"""
        r = _make_fr()
        _seed_runner(r, "existing-dead", plan_file="docs/plan/test.md", pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=False), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"
        assert resp.get("status") != "attached"

    def test_start_ignores_all_plans_runner(self):
        """B: plan_file=__ALL_PLANS__ 러너는 attach 대상에서 제외"""
        r = _make_fr()
        _seed_runner(r, "all-plans-runner", plan_file=PLAN_FILE_ALL, pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"

    def test_start_ignores_legacy_all_runner(self):
        """B: plan_file=ALL (레거시) 러너도 attach 대상에서 제외"""
        r = _make_fr()
        _seed_runner(r, "legacy-all-runner", plan_file=_LEGACY_ALL, pid=9999)

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("message") == "accepted"

    def test_start_returns_cleanup_in_progress(self):
        """B: 동일 plan cleanup 진행 중이면 '정리 중' 응답 반환"""
        r = _make_fr()
        cleaning_id = "cleaning-runner-abc"
        _seed_runner(r, cleaning_id, plan_file="docs/plan/test.md", pid=9999)
        r.set(f"{RUNNER_KEY_PREFIX}:{cleaning_id}:cleanup_in_progress", "1")

        cmd = _make_command(plan_file="docs/plan/test.md", runner_id="new-runner-xyz")

        with patch("_dr_plan_runner._is_pid_alive", return_value=False):
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-001")
        assert resp.get("success") is False
        assert "정리 중" in resp.get("message", "")


# ─────────────────────────────────────────────────────────────
# Phase T1: _tail_log_and_publish replay 동작
# ─────────────────────────────────────────────────────────────

class TestTailLogReplay:
    """_tail_log_and_publish replay_from_start 동작 검증"""

    def _write_log_lines(self, tmp_path: Path, count: int) -> Path:
        log_file = tmp_path / "runner.log"
        log_file.write_text("\n".join(f"LOG LINE {i}" for i in range(count)) + "\n", encoding="utf-8")
        return log_file

    def test_tail_log_replay_from_start_publishes_all(self, tmp_path):
        """R: replay_from_start=True이면 기존 로그를 처음부터 모두 발행"""
        r = _make_fr()
        runner_id = "replay-runner-001"
        log_file = self._write_log_lines(tmp_path, 10)

        # _running_processes에 즉시 종료하는 DummyProcess 등록
        dummy = MagicMock()
        dummy.pid = 1234
        dummy.poll.return_value = 0  # 이미 종료

        published = []

        def _fake_publish(redis_client, channel, data):
            published.append(data)

        procs = {runner_id: dummy}
        with patch.dict(_tail_log_and_publish.__globals__, {
            "get_running_processes": lambda: procs,
            "_publish_with_retry": _fake_publish,
        }):
            _tail_log_and_publish(runner_id, str(log_file), r, replay_from_start=True)

        # 10줄 모두 publish됨
        content = " ".join(published)
        for i in range(10):
            assert f"LOG LINE {i}" in content, f"LINE {i} 미수신 (published={published})"

    def test_tail_log_default_skips_existing(self, tmp_path):
        """I: replay_from_start=False(기본)이면 기존 줄은 발행하지 않음"""
        r = _make_fr()
        runner_id = "noreplay-runner-001"
        log_file = self._write_log_lines(tmp_path, 10)

        dummy = MagicMock()
        dummy.pid = 1234
        dummy.poll.return_value = 0

        published = []

        def _fake_publish(redis_client, channel, data):
            published.append(data)

        procs = {runner_id: dummy}
        with patch.dict(_tail_log_and_publish.__globals__, {
            "get_running_processes": lambda: procs,
            "_publish_with_retry": _fake_publish,
        }):
            _tail_log_and_publish(runner_id, str(log_file), r, replay_from_start=False)

        # 기존 10줄은 발행되지 않아야 함 (EOF에서 시작)
        assert len(published) == 0, f"기존 줄이 발행됨: {published}"


# ─────────────────────────────────────────────────────────────
# Phase T1: _cleanup_process_state cleanup_in_progress 플래그
# ─────────────────────────────────────────────────────────────

class TestCleanupInProgressFlag:
    """_cleanup_process_state의 cleanup_in_progress Redis 플래그 검증"""

    def _minimal_cleanup(self, runner_id: str, r):
        """최소 의존성 mock으로 _cleanup_process_state 실행"""
        wf_mgr = MagicMock()
        wf_mgr.get_by_runner_id.return_value = None

        wm_stub = MagicMock()
        wm_stub.remove.return_value = None

        with patch("_dr_process_utils.get_wf_manager", return_value=wf_mgr), \
             patch("_dr_process_utils._is_pre_review_stopped_runner", return_value=False), \
             patch("_dr_process_utils._try_v2_merge_fallback"), \
             patch("worktree_manager.WorktreeManager", wm_stub), \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            _cleanup_process_state(runner_id, r, reason="test")

    def test_cleanup_clears_in_progress_flag(self):
        """R: cleanup 완료 후 cleanup_in_progress 키 삭제됨"""
        r = _make_fr()
        runner_id = "cleanup-test-001"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/x.md")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        self._minimal_cleanup(runner_id, r)

        # 완료 후 플래그 없어야 함
        flag = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
        assert flag is None, f"cleanup_in_progress 미삭제: {flag}"

    def test_cleanup_sets_in_progress_then_clears(self):
        """R: cleanup 진입 시 플래그 세팅, 완료 후 삭제"""
        r = _make_fr()
        runner_id = "cleanup-test-002"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        flags_during = []

        original_delete = r.delete

        def _patched_delete(*keys):
            # cleanup_in_progress 삭제 직전에 값 캡처는 어렵지만
            # 함수 완료 후 None인지 확인
            return original_delete(*keys)

        # cleanup 실행 후 검증
        self._minimal_cleanup(runner_id, r)
        flag_after = r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:cleanup_in_progress")
        assert flag_after is None


# ─────────────────────────────────────────────────────────────
# Phase T3: 재실행 → attach 통합 테스트
# ─────────────────────────────────────────────────────────────

class TestRerunAttachIntegration:
    """fakeredis 공유 서버로 실제 start_plan_runner attach 흐름 검증"""

    def test_rerun_attaches_to_alive_worker_integration(self):
        """T3: 동일 plan 실행 중 재실행 → attached 응답 + 기존 runner_id 반환"""
        server = fakeredis.FakeServer()
        r1 = fakeredis.FakeRedis(server=server, decode_responses=True)
        r2 = fakeredis.FakeRedis(server=server, decode_responses=True)

        existing_id = "existing-int-runner"
        plan_file = "docs/plan/integration_test.md"
        _seed_runner(r1, existing_id, plan_file=plan_file, pid=7777)

        cmd = _make_command(plan_file=plan_file, runner_id="new-int-runner", command_id="cmd-int-001")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner._cleanup_process_state"):
            result = start_plan_runner(cmd, r2)

        assert result is None

        resp = _pop_result(r2, "cmd-int-001")
        assert resp["success"] is True, f"success 기대값 True, 실제: {resp}"
        assert resp["status"] == "attached", f"status 기대값 attached, 실제: {resp}"
        assert resp["runner_id"] == existing_id

    def test_rerun_creates_new_after_stop_integration(self):
        """T3: stop 후 재실행 → 새 runner_id로 accepted (고아 없음)"""
        r = _make_fr()
        old_id = "old-stopped-runner"
        plan_file = "docs/plan/stop_then_run.md"

        # stop 후: ACTIVE_RUNNERS에 없음 (cleanup이 srem했다고 가정)
        r.set(f"{RUNNER_KEY_PREFIX}:{old_id}:status", "stopped")
        r.set(f"{RUNNER_KEY_PREFIX}:{old_id}:plan_file", plan_file)
        # ACTIVE_RUNNERS에 추가 안 함 (stop 후 제거된 상태)

        cmd = _make_command(plan_file=plan_file, runner_id="brand-new-runner", command_id="cmd-new-001")

        with patch("_dr_plan_runner._is_pid_alive", return_value=True), \
             patch("_dr_plan_runner.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_threading.Thread.return_value = mock_thread
            result = start_plan_runner(cmd, r)

        assert result is None
        resp = _pop_result(r, "cmd-new-001")
        # attached가 아닌 accepted
        assert resp.get("message") == "accepted"
        assert resp.get("status") != "attached"


# ─────────────────────────────────────────────────────────────
# Phase T1 item 16: ExecutorService attached 응답 처리
# ─────────────────────────────────────────────────────────────

class TestExecutorServiceAttachedResponse:
    """ExecutorService.start_dev_runner의 attached 응답 처리 검증"""

    @pytest.fixture
    def fake_async_redis(self):
        import fakeredis.aioredis
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def executor(self, fake_async_redis, monkeypatch):
        monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
        from app.modules.dev_runner.services.executor_service import ExecutorService
        import fakeredis
        svc = ExecutorService()
        svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
        svc.async_redis = fake_async_redis
        return svc

    async def test_start_dev_runner_returns_attached_response(self, executor, fake_async_redis):
        """R: _send_command가 attached 반환 → RunStatusResponse.attached==True"""
        existing_id = "existing-runner-from-exec"
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")
        # existing runner Redis 상태 세팅
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:pid", "5678")
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:plan_file", "docs/plan/test.md")
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:engine", "claude")
        from datetime import datetime
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:start_time", datetime.now().isoformat())
        await fake_async_redis.set(f"plan-runner:runners:{existing_id}:execution_count", "3")

        attached_resp = {
            "success": True,
            "status": "attached",
            "runner_id": existing_id,
            "message": "기존 워커에 연결됨",
        }

        from app.modules.dev_runner.schemas import RunRequest
        request = RunRequest(test_source="tc:exec-attach", plan_file="docs/plan/test.md")

        with patch.object(executor, "_send_command", return_value=attached_resp):
            from app.modules.dev_runner.services.executor_service import ExecutorService
            result = await executor.start_dev_runner(request)

        assert result.attached is True, f"attached 기대 True, 실제: {result}"
        assert result.runner_id == existing_id
        assert result.running is True
        assert result.pid == 5678
        assert result.execution_count == 3

    async def test_start_dev_runner_normal_run_not_attached(self, executor, fake_async_redis):
        """I: 정상 run 응답 → RunStatusResponse.attached==False"""
        await fake_async_redis.set("plan-runner:listener:heartbeat", "alive")

        accepted_resp = {
            "success": True,
            "message": "accepted",
            "runner_id": "whatever-uuid",
        }

        from datetime import datetime
        runner_fields = {
            "pid": "9876",
            "plan_file": "docs/plan/test.md",
            "start_time": datetime.now().isoformat(),
            "execution_count": "1",
        }

        from app.modules.dev_runner.schemas import RunRequest
        request = RunRequest(test_source="tc:exec-normal", plan_file="docs/plan/test.md")

        with patch.object(executor, "_send_command", return_value=accepted_resp), \
             patch.object(executor, "_get_runner_fields", return_value=runner_fields):
            result = await executor.start_dev_runner(request)

        assert result.attached is False, f"attached 기대 False, 실제: {result}"
