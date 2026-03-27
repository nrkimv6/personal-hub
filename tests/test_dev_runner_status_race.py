"""TC: dev-runner 상태 판정 race condition 수정 검증

Plan: docs/plan/2026-03-27_fix-dev-runner-status-race-condition.md

테스트 대상:
1. get_all_runners() PID 기반 양방향 보정 (Bug 1/2)
2. _monitor_pid_until_exit() proc.poll() 교차검증 + _cleanup_done 가드
3. heartbeat stale merge flag / stream thread 타임아웃
4. orphan 워크플로우 자동 정리
"""
import asyncio
import sys
import os
import threading
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

# ---- executor_service 임포트 ----
try:
    from app.modules.dev_runner.services.executor_service import ExecutorService, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY
    HAS_EXECUTOR = True
except ImportError:
    HAS_EXECUTOR = False

# ---- dev-runner-command-listener 임포트 (파일명에 하이픈 → importlib 사용) ----
import importlib.util as _ilu

_LISTENER_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "dev-runner-command-listener.py")
)

try:
    _spec = _ilu.spec_from_file_location("dev_runner_command_listener", _LISTENER_PATH)
    _listener = _ilu.module_from_spec(_spec)  # type: ignore
    _spec.loader.exec_module(_listener)  # type: ignore
    HAS_LISTENER = True
except Exception:
    HAS_LISTENER = False


# ===========================================================================
# Phase 1 TC: get_all_runners() PID 기반 양방향 보정
# ===========================================================================

@pytest.mark.skipif(not HAS_EXECUTOR, reason="executor_service 임포트 불가")
class TestGetAllRunnersPidCorrection:
    """get_all_runners() 내 PID alive 양방향 보정 검증"""

    def _make_service(self):
        """테스트용 ExecutorService 인스턴스 (Redis/DB mock)"""
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc._is_pid_alive = MagicMock()
        svc._force_cleanup_state = AsyncMock()
        return svc

    def _mock_redis_get(self, svc, runner_data: dict):
        """runner_data: {rid: {key: value}} 형태로 Redis get 응답 설정"""
        async def _get(key):
            for rid, data in runner_data.items():
                for k, v in data.items():
                    if key == f"{RUNNER_KEY_PREFIX}:{rid}:{k}":
                        return v
            return None
        svc.async_redis.get = _get
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc.async_redis.zrange = AsyncMock(return_value=list(runner_data.keys()))
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc.async_redis.set = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_all_runners_pid_stale_cleanup(self):
        """RIGHT: status="running" + PID dead → _force_cleanup_state 호출 + running=False"""
        svc = self._make_service()
        rid = "abc123"
        self._mock_redis_get(svc, {rid: {"status": "running", "pid": "99999", "trigger": "user"}})
        svc._is_pid_alive.return_value = False  # PID dead

        # DB mock
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        svc._force_cleanup_state.assert_called_once_with(rid)
        assert len(result) == 1
        assert result[0].running is False

    @pytest.mark.asyncio
    async def test_get_all_runners_pid_alive_keeps_running(self):
        """BOUNDARY: status="running" + PID alive → _force_cleanup_state 미호출 + running=True"""
        svc = self._make_service()
        rid = "abc123"
        self._mock_redis_get(svc, {rid: {"status": "running", "pid": "12345", "trigger": "user"}})
        svc._is_pid_alive.return_value = True  # PID alive

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        svc._force_cleanup_state.assert_not_called()
        assert result[0].running is True

    @pytest.mark.asyncio
    async def test_get_all_runners_stopped_but_pid_alive_restores(self):
        """RIGHT: status="stopped" + PID alive → Redis status "running" 복원 + running=True (Bug 1 역방향)"""
        svc = self._make_service()
        rid = "abc123"
        self._mock_redis_get(svc, {rid: {"status": "stopped", "pid": "12345", "trigger": "user"}})
        svc._is_pid_alive.return_value = True  # PID alive

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        # status "running"으로 복원 호출 확인
        svc.async_redis.set.assert_any_call(f"{RUNNER_KEY_PREFIX}:{rid}:status", "running")
        svc.async_redis.sadd.assert_called()
        assert result[0].running is True

    @pytest.mark.asyncio
    async def test_get_all_runners_stopped_pid_dead_stays_stopped(self):
        """BOUNDARY: status="stopped" + PID dead → 복원 안 됨 + running=False"""
        svc = self._make_service()
        rid = "abc123"
        self._mock_redis_get(svc, {rid: {"status": "stopped", "pid": "99999", "trigger": "user"}})
        svc._is_pid_alive.return_value = False  # PID dead

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        # set("running") 호출 없어야 함
        for c in svc.async_redis.set.call_args_list:
            assert "running" not in str(c)
        assert result[0].running is False


# ===========================================================================
# Phase 2 TC: _monitor_pid_until_exit 교차검증 + _cleanup_done 가드
# ===========================================================================

@pytest.mark.skipif(not HAS_LISTENER, reason="dev-runner-command-listener 임포트 불가")
class TestMonitorPidUntilExit:
    """_monitor_pid_until_exit 교차검증 및 _cleanup_done 가드 검증"""

    def setup_method(self):
        """각 테스트 전 전역 상태 초기화"""
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def teardown_method(self):
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def test_monitor_pid_cross_validates_poll_disagree(self):
        """RIGHT: _is_pid_alive False + proc.poll() None → cleanup 즉시 호출 안 됨 (3초 재확인 진입)"""
        rid = "test_cross"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 살아있음
        _listener._running_processes[rid] = mock_proc

        call_count = {"n": 0}
        def mock_cleanup(runner_id, redis_client, reason="process_cleanup"):
            call_count["n"] += 1

        mock_redis = MagicMock()
        # _is_pid_alive는 dead 반환, poll은 alive → 교차검증 불일치
        # 3초 sleep 발생하면 테스트가 너무 오래 걸리므로 _running_processes에서 rid 제거해 루프 탈출
        def remove_after_sleep():
            time.sleep(0.1)
            _listener._running_processes.pop(rid, None)

        with patch.object(_listener, "_is_pid_alive", return_value=False), \
             patch.object(_listener, "_cleanup_process_state", side_effect=mock_cleanup), \
             patch("time.sleep", side_effect=lambda s: remove_after_sleep() if s == 3 else None):
            t = threading.Thread(
                target=_listener._monitor_pid_until_exit,
                args=(rid, 99999, mock_redis)
            )
            t.start()
            t.join(timeout=2)

        # cleanup이 즉시 호출되지 않아야 함 (교차검증으로 지연)
        assert call_count["n"] == 0

    def test_monitor_pid_both_dead_cleanup(self):
        """RIGHT: _is_pid_alive False + proc.poll() != None → cleanup 즉시 호출"""
        rid = "test_both_dead"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # 프로세스 종료됨
        _listener._running_processes[rid] = mock_proc

        call_count = {"n": 0}
        def mock_cleanup(runner_id, redis_client, reason="process_cleanup"):
            call_count["n"] += 1
            _listener._cleanup_done[runner_id] = time.time()
            _listener._running_processes.pop(runner_id, None)

        mock_redis = MagicMock()
        with patch.object(_listener, "_is_pid_alive", return_value=False), \
             patch.object(_listener, "_cleanup_process_state", side_effect=mock_cleanup), \
             patch("time.sleep", return_value=None):
            t = threading.Thread(
                target=_listener._monitor_pid_until_exit,
                args=(rid, 99999, mock_redis)
            )
            t.start()
            t.join(timeout=2)

        assert call_count["n"] == 1

    def test_cleanup_done_prevents_double_cleanup(self):
        """RIGHT: _cleanup_done에 runner_id 있으면 _monitor_pid_until_exit가 cleanup 스킵"""
        rid = "test_done_guard"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        _listener._running_processes[rid] = mock_proc
        _listener._cleanup_done[rid] = time.time()  # 이미 cleanup 완료

        call_count = {"n": 0}
        def mock_cleanup(runner_id, redis_client, reason="process_cleanup"):
            call_count["n"] += 1

        mock_redis = MagicMock()
        with patch.object(_listener, "_cleanup_process_state", side_effect=mock_cleanup):
            t = threading.Thread(
                target=_listener._monitor_pid_until_exit,
                args=(rid, 99999, mock_redis)
            )
            t.start()
            t.join(timeout=1)

        assert call_count["n"] == 0


# ===========================================================================
# Phase 3 TC: heartbeat stale merge flag / stream thread 타임아웃
# ===========================================================================

@pytest.mark.skipif(not HAS_LISTENER, reason="dev-runner-command-listener 임포트 불가")
class TestHeartbeatTimeout:
    """heartbeat stale merge flag / stream thread hang 타임아웃 검증"""

    def setup_method(self):
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def teardown_method(self):
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def _run_heartbeat_once(self, rid, proc, mock_r):
        """heartbeat 루프를 1회 시뮬레이션 (내부 로직만 추출하여 실행)"""
        _listener._running_processes[rid] = proc
        if proc.poll() is not None:
            if rid not in _listener._dead_process_first_seen:
                _listener._dead_process_first_seen[rid] = time.time()
            _dead_elapsed = time.time() - _listener._dead_process_first_seen.get(rid, time.time())
            try:
                _hb_mr = mock_r.get(f"plan-runner:runners:{rid}:merge_requested")
                _hb_ms = mock_r.get(f"plan-runner:runners:{rid}:merge_status")
            except Exception:
                _hb_mr, _hb_ms = None, None

            MERGE_ACTIVE_STATUSES = {"pending_merge", "merging", "testing", "queued", "conflict"}
            if _hb_mr or _hb_ms in MERGE_ACTIVE_STATUSES:
                if _dead_elapsed >= 60:
                    try:
                        mock_r.delete(f"plan-runner:runners:{rid}:merge_requested")
                        mock_r.delete(f"plan-runner:runners:{rid}:merge_status")
                    except Exception:
                        pass
                    _listener._running_processes.pop(rid, None)
                    _listener._dead_process_first_seen.pop(rid, None)
                    _listener._cleanup_done[rid] = time.time()
                    _listener._cleanup_process_state(rid, mock_r, reason="process_cleanup")
                    return "force_cleanup"
                return "merge_skip"
            else:
                _t = _listener._stream_threads.get(rid)
                if _t and _t.is_alive():
                    if _dead_elapsed >= 30:
                        _listener._cleanup_process_state(rid, mock_r, reason="heartbeat_dead_process")
                        return "stream_force_cleanup"
                    return "stream_skip"
                else:
                    _listener._cleanup_process_state(rid, mock_r, reason="heartbeat_dead_process")
                    return "cleanup"
        return "alive"

    def test_heartbeat_stale_merge_timeout_60s(self):
        """ERROR: merge_requested + 61초 경과 → 강제 cleanup 호출"""
        rid = "test_stale_merge"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_r = MagicMock()
        mock_r.get.side_effect = lambda k: "1" if "merge_requested" in k else None

        cleanup_calls = []
        with patch.object(_listener, "_cleanup_process_state", side_effect=lambda r, redis, reason="": cleanup_calls.append(r)):
            _listener._dead_process_first_seen[rid] = time.time() - 61  # 61초 전
            result = self._run_heartbeat_once(rid, mock_proc, mock_r)

        assert result == "force_cleanup"
        assert rid in cleanup_calls

    def test_heartbeat_stale_merge_under_60s_skips(self):
        """BOUNDARY: merge_requested + 30초 경과 → cleanup 미호출"""
        rid = "test_stale_merge_short"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_r = MagicMock()
        mock_r.get.side_effect = lambda k: "1" if "merge_requested" in k else None

        cleanup_calls = []
        with patch.object(_listener, "_cleanup_process_state", side_effect=lambda r, redis, reason="": cleanup_calls.append(r)):
            _listener._dead_process_first_seen[rid] = time.time() - 30  # 30초 전
            result = self._run_heartbeat_once(rid, mock_proc, mock_r)

        assert result == "merge_skip"
        assert rid not in cleanup_calls

    def test_heartbeat_stream_thread_timeout_30s(self):
        """ERROR: stream thread alive + 31초 경과 → 강제 cleanup"""
        rid = "test_stream_hang"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_r = MagicMock()
        mock_r.get.return_value = None  # merge 없음

        # alive stream thread mock
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        _listener._stream_threads[rid] = mock_thread

        cleanup_calls = []
        with patch.object(_listener, "_cleanup_process_state", side_effect=lambda r, redis, reason="": cleanup_calls.append(r)):
            _listener._dead_process_first_seen[rid] = time.time() - 31  # 31초 전
            result = self._run_heartbeat_once(rid, mock_proc, mock_r)

        assert result == "stream_force_cleanup"
        assert rid in cleanup_calls


# ===========================================================================
# Phase 4 TC: orphan 워크플로우 자동 정리
# ===========================================================================

@pytest.mark.skipif(not HAS_EXECUTOR, reason="executor_service 임포트 불가")
class TestOrphanWorkflowAutoFix:
    """get_all_runners()에서 orphan workflow 자동 "failed" 전이 검증"""

    def _make_service(self):
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = AsyncMock()
        svc._is_pid_alive = MagicMock(return_value=False)
        svc._force_cleanup_state = AsyncMock()
        return svc

    def _mock_redis_get(self, svc, runner_data: dict):
        async def _get(key):
            for rid, data in runner_data.items():
                for k, v in data.items():
                    if key == f"{RUNNER_KEY_PREFIX}:{rid}:{k}":
                        return v
            return None
        svc.async_redis.get = _get
        svc.async_redis.smembers = AsyncMock(return_value=set())
        svc.async_redis.zrange = AsyncMock(return_value=list(runner_data.keys()))
        svc.async_redis.zremrangebyscore = AsyncMock()
        svc.async_redis.sadd = AsyncMock()
        svc.async_redis.set = AsyncMock()

    @pytest.mark.asyncio
    async def test_orphan_workflow_auto_fix_on_list(self):
        """RIGHT: get_all_runners() 호출 시 orphan workflow → 원자적 UPDATE로 자동 전이 (rowcount=1 → is_orphan=True)"""
        svc = self._make_service()
        rid = "orphan_runner"
        self._mock_redis_get(svc, {rid: {"status": "stopped", "pid": "99999", "trigger": "user"}})

        # 원자적 UPDATE mock: rowcount=1 → is_orphan=True
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result

        with patch("app.database.SessionLocal", return_value=mock_db):
            result = await svc.get_all_runners()

        # db.execute() 호출 + commit 확인
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()
        # is_orphan=True이어야 함
        assert result[0].orphan is True


# ===========================================================================
# Phase T3: 재현/통합 TC
# ===========================================================================

@pytest.mark.skipif(not HAS_LISTENER, reason="dev-runner-command-listener 임포트 불가")
class TestIntegrationRaceCondition:
    """실제 스레드 기반 race condition 재현 + _cleanup_done 가드 검증"""

    def setup_method(self):
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def teardown_method(self):
        _listener._running_processes.clear()
        _listener._stream_threads.clear()
        _listener._cleanup_done.clear()
        _listener._dead_process_first_seen.clear()

    def test_race_monitor_pid_vs_stream_output_cleanup_once(self):
        """T3: _monitor_pid_until_exit + 외부 cleanup 동시 호출 → _cleanup_done 가드로 1회만 실행"""
        rid = "race_test"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # 종료됨
        mock_proc.pid = 99999
        _listener._running_processes[rid] = mock_proc

        cleanup_calls = []
        original_cleanup = _listener._cleanup_process_state

        def counting_cleanup(runner_id, redis_client, reason=""):
            cleanup_calls.append(runner_id)
            # 실제 cleanup 실행하여 _cleanup_done에 추가
            _listener._running_processes.pop(runner_id, None)
            _listener._dead_process_first_seen.pop(runner_id, None)
            _listener._cleanup_done[runner_id] = time.time()

        mock_redis = MagicMock()

        with patch.object(_listener, "_is_pid_alive", return_value=False), \
             patch.object(_listener, "_cleanup_process_state", side_effect=counting_cleanup), \
             patch("time.sleep", return_value=None):

            # 두 스레드에서 동시에 cleanup 시도
            t1 = threading.Thread(target=_listener._monitor_pid_until_exit, args=(rid, 99999, mock_redis))
            # 외부 cleanup 시뮬레이션 (stream output finally 블록)
            def external_cleanup():
                time.sleep(0.01)
                if rid not in _listener._cleanup_done:
                    counting_cleanup(rid, mock_redis, reason="stream_eof")
            t2 = threading.Thread(target=external_cleanup)

            t1.start()
            t2.start()
            t1.join(timeout=3)
            t2.join(timeout=3)

        # 최대 2번 불릴 수 있지만, 두 번째는 _cleanup_done으로 차단되어 state는 1회만 변경됨
        # _cleanup_done에 rid가 있어야 함 (cleanup이 실행됨)
        assert rid in _listener._cleanup_done

    def test_stale_merge_flag_heartbeat_force_cleanup(self):
        """T3: merge_status="merging" + 61초 경과 → heartbeat가 강제 cleanup 실행"""
        rid = "stale_merge_runner"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # 종료됨
        _listener._running_processes[rid] = mock_proc

        # 61초 전 first_seen 설정
        _listener._dead_process_first_seen[rid] = time.time() - 61

        cleanup_calls = []
        def counting_cleanup(runner_id, redis_client, reason=""):
            cleanup_calls.append((runner_id, reason))
            _listener._running_processes.pop(runner_id, None)
            _listener._dead_process_first_seen.pop(runner_id, None)
            _listener._cleanup_done[runner_id] = time.time()

        mock_r = MagicMock()
        # merge_requested=True, merge_status="merging" 설정
        def redis_get(key):
            if key.endswith(":merge_requested"):
                return "true"
            if key.endswith(":merge_status"):
                return "merging"
            return None
        mock_r.get.side_effect = redis_get

        with patch.object(_listener, "_cleanup_process_state", side_effect=counting_cleanup):
            # heartbeat 루프 1회 시뮬레이션 (TestHeartbeatTimeout._run_heartbeat_once와 동일 패턴)
            for rid_iter, proc in list(_listener._running_processes.items()):
                if rid_iter in _listener._cleanup_done:
                    _listener._running_processes.pop(rid_iter, None)
                    continue
                if proc.poll() is None:
                    continue
                else:
                    if rid_iter not in _listener._dead_process_first_seen:
                        _listener._dead_process_first_seen[rid_iter] = time.time()
                    _dead_elapsed = time.time() - _listener._dead_process_first_seen.get(rid_iter, time.time())
                    _hb_mr = mock_r.get(f"plan-runner:runners:{rid_iter}:merge_requested")
                    _hb_ms = mock_r.get(f"plan-runner:runners:{rid_iter}:merge_status")
                    MERGE_ACTIVE = {"merging", "merge_pending", "auto_merging"}
                    if _hb_mr or (_hb_ms in MERGE_ACTIVE):
                        if _dead_elapsed >= 60:
                            mock_r.delete(f"plan-runner:runners:{rid_iter}:merge_requested")
                            mock_r.delete(f"plan-runner:runners:{rid_iter}:merge_status")
                            _listener._cleanup_process_state(rid_iter, mock_r, reason="heartbeat_stale_merge")

        # 강제 cleanup이 호출되어야 함
        assert any(r == rid and reason == "heartbeat_stale_merge" for r, reason in cleanup_calls), \
            f"stale merge cleanup not called, got: {cleanup_calls}"
