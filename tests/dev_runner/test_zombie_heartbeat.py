"""좀비 runner heartbeat 감지/복구 TC."""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from tests.dev_runner._path_helpers import (
    bootstrap_plan_runner_modules,
    load_listener_module,
)


_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    _listener_mod = load_listener_module("dev_runner_command_listener_zombie")
    return _listener_mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


@pytest.fixture(scope="module")
def process_utils_mod():
    _state_mod, process_utils = bootstrap_plan_runner_modules()
    return process_utils


@pytest.fixture(scope="module")
def state_mod():
    state, _process_utils_mod = bootstrap_plan_runner_modules()
    return state


@pytest.fixture(autouse=True)
def reset_state(state_mod):
    state_mod.get_running_processes().clear()
    state_mod.get_running_log_files().clear()
    state_mod.get_stream_threads().clear()
    state_mod.get_cleanup_done().clear()
    state_mod.get_dead_process_first_seen().clear()
    state_mod.get_zombie_first_seen().clear()
    yield
    state_mod.get_running_processes().clear()
    state_mod.get_running_log_files().clear()
    state_mod.get_stream_threads().clear()
    state_mod.get_cleanup_done().clear()
    state_mod.get_dead_process_first_seen().clear()
    state_mod.get_zombie_first_seen().clear()


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"


def _seed_active_runner(fr, runner_id: str, pid: int, start_time: str, with_heartbeat: bool = False):
    fr.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", start_time)
    if with_heartbeat:
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", str(time.time()), ex=120)


def _seed_orphan_runner(fr, runner_id: str, pid: int, start_time: str, with_heartbeat: bool = False):
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", start_time)
    if with_heartbeat:
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", str(time.time()), ex=120)


def test_reconnect_zombie_pid_alive_no_heartbeat(listener_mod, process_utils_mod, fr):
    """R(Right): PID alive + heartbeat 없음(오래된 start_time) -> reconnect_zombie cleanup."""
    runner_id = "zombie-reconnect-1"
    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    _seed_active_runner(fr, runner_id, pid=4321, start_time=old_start, with_heartbeat=False)

    with patch.object(process_utils_mod, "_is_pid_alive", return_value=True), \
         patch.object(process_utils_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(process_utils_mod, "_attach_to_running_process") as mock_attach:
        listener_mod._reconnect_surviving_runners(fr)

    mock_cleanup.assert_called_once_with(runner_id, fr, reason="reconnect_zombie")
    mock_attach.assert_not_called()


def test_reconnect_healthy_pid_alive_with_heartbeat(listener_mod, process_utils_mod, fr):
    """R(Right): PID alive + heartbeat 존재 -> 재연결."""
    runner_id = "healthy-reconnect-1"
    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    _seed_active_runner(fr, runner_id, pid=5678, start_time=old_start, with_heartbeat=True)

    with patch.object(process_utils_mod, "_is_pid_alive", return_value=True), \
         patch.object(process_utils_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(process_utils_mod, "_attach_to_running_process") as mock_attach:
        listener_mod._reconnect_surviving_runners(fr)

    mock_cleanup.assert_not_called()
    mock_attach.assert_called_once_with(runner_id, 5678, fr)


def test_reconnect_orphan_zombie_cleanup(listener_mod, process_utils_mod, fr):
    """R(Right): orphan scan에서 PID alive + heartbeat 없음 -> reconnect_zombie cleanup."""
    orphan_id = "orphan-zombie-1"
    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    _seed_orphan_runner(fr, orphan_id, pid=7777, start_time=old_start, with_heartbeat=False)

    with patch.object(process_utils_mod, "_is_pid_alive", return_value=True), \
         patch.object(process_utils_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(process_utils_mod, "_attach_to_running_process") as mock_attach:
        listener_mod._reconnect_surviving_runners(fr)

    mock_cleanup.assert_called_once_with(orphan_id, fr, reason="reconnect_zombie")
    mock_attach.assert_not_called()


def test_reconnect_legacy_runner_skip(listener_mod, process_utils_mod, fr):
    """B(Boundary): 최근 start_time(<10분) + heartbeat 없음 -> 레거시 보호 fallback."""
    runner_id = "legacy-skip-1"
    recent_start = (datetime.now() - timedelta(minutes=3)).isoformat()
    _seed_active_runner(fr, runner_id, pid=8765, start_time=recent_start, with_heartbeat=False)

    with patch.object(process_utils_mod, "_is_pid_alive", return_value=True), \
         patch.object(process_utils_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(process_utils_mod, "_attach_to_running_process") as mock_attach:
        listener_mod._reconnect_surviving_runners(fr)

    mock_cleanup.assert_not_called()
    mock_attach.assert_called_once_with(runner_id, 8765, fr)


def test_heartbeat_sweep_detects_zombie(listener_mod, state_mod, fr):
    """R(Right): sweep helper가 grace 초과 좀비를 강제 정리한다."""
    runner_id = "hb-zombie-1"
    proc = MagicMock()
    proc.pid = 9911

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", old_start)
    state_mod.get_running_processes()[runner_id] = proc
    state_mod.get_zombie_first_seen()[runner_id] = time.time() - listener_mod.ZOMBIE_GRACE_SECONDS - 1

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_pub_and_log"):
        cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert cleaned is True
    proc.kill.assert_called_once()
    mock_cleanup.assert_called_once_with(runner_id, fr, reason="zombie_heartbeat_timeout")
    assert runner_id not in state_mod.get_zombie_first_seen()


def test_heartbeat_sweep_spares_healthy_runner(listener_mod, state_mod, fr):
    """R(Right): heartbeat가 정상인 runner는 좀비로 분류되지 않는다."""
    runner_id = "hb-healthy-1"
    proc = MagicMock()
    proc.pid = 9912

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", old_start)
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", str(time.time()), ex=120)
    state_mod.get_running_processes()[runner_id] = proc

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
        cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert cleaned is False
    mock_cleanup.assert_not_called()
    assert runner_id not in state_mod.get_zombie_first_seen()


def test_heartbeat_sweep_grace_period(listener_mod, state_mod, fr):
    """B(Boundary): grace 미달은 정리하지 않고, grace 초과 시 정리한다."""
    runner_id = "hb-grace-1"
    proc = MagicMock()
    proc.pid = 9913

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", old_start)
    state_mod.get_running_processes()[runner_id] = proc

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup, \
         patch.object(listener_mod, "_pub_and_log"):
        first = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)
        assert first is False
        mock_cleanup.assert_not_called()
        assert runner_id in state_mod.get_zombie_first_seen()

        state_mod.get_zombie_first_seen()[runner_id] = time.time() - listener_mod.ZOMBIE_GRACE_SECONDS - 1
        second = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert second is True
    mock_cleanup.assert_called_once_with(runner_id, fr, reason="zombie_heartbeat_timeout")


def test_heartbeat_sweep_zombie_recovery(listener_mod, state_mod, fr):
    """B(Boundary): 좀비 후보 등록 후 heartbeat 복귀하면 후보 목록에서 제거된다."""
    runner_id = "hb-recover-1"
    proc = MagicMock()
    proc.pid = 9914

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", old_start)
    state_mod.get_running_processes()[runner_id] = proc

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
        first = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)
        assert first is False
        assert runner_id in state_mod.get_zombie_first_seen()
        mock_cleanup.assert_not_called()

        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", str(time.time()), ex=120)
        second = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert second is False
    assert runner_id not in state_mod.get_zombie_first_seen()
    mock_cleanup.assert_not_called()


def test_heartbeat_sweep_legacy_runner_skip(listener_mod, state_mod, fr):
    """R(Right): 최근 start_time(<10분) runner는 heartbeat 없음이어도 sweep에서 좀비 스킵."""
    runner_id = "hb-legacy-1"
    proc = MagicMock()
    proc.pid = 9922

    recent_start = (datetime.now() - timedelta(minutes=2)).isoformat()
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", recent_start)
    state_mod.get_running_processes()[runner_id] = proc

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
        cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert cleaned is False
    mock_cleanup.assert_not_called()
    assert runner_id in state_mod.get_running_processes()
    assert runner_id not in state_mod.get_zombie_first_seen()


def test_heartbeat_sweep_cleanup_done_skip(listener_mod, state_mod, fr):
    """B(Boundary): cleanup_done 등록된 runner는 heartbeat 체크를 건너뛴다."""
    runner_id = "hb-cleanup-done-1"
    proc = MagicMock()
    proc.pid = 9929

    state_mod.get_running_processes()[runner_id] = proc
    state_mod.get_cleanup_done()[runner_id] = time.time()

    with patch.object(listener_mod, "_handle_zombie_heartbeat") as mock_handle:
        result = listener_mod._handle_running_process_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert result == "skipped_cleanup_done"
    mock_handle.assert_not_called()
    assert runner_id not in state_mod.get_running_processes()


def test_new_runner_not_detected_as_zombie(listener_mod, state_mod, fr):
    """R(Right): heartbeat 키가 있으면 sweep에서 좀비로 분류하지 않는다."""
    runner_id = "hb-new-1"
    proc = MagicMock()
    proc.pid = 9933

    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat", str(time.time()), ex=300)
    state_mod.get_running_processes()[runner_id] = proc
    state_mod.get_zombie_first_seen()[runner_id] = time.time() - 100

    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
        cleaned = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert cleaned is False
    mock_cleanup.assert_not_called()
    assert runner_id in state_mod.get_running_processes()
    assert runner_id not in state_mod.get_zombie_first_seen()


def test_zombie_runner_full_lifecycle(listener_mod, state_mod, fr):
    """T3: 좀비 후보 등록 → grace 초과 후 cleanup + workflow failed 반영까지 검증."""
    runner_id = "hb-lifecycle-1"
    proc = MagicMock()
    proc.pid = 9941

    old_start = (datetime.now() - timedelta(minutes=20)).isoformat()
    fr.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(proc.pid))
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", old_start)
    state_mod.get_running_processes()[runner_id] = proc

    class _FakeWfManager:
        def __init__(self):
            self.updated = []

        def get_by_runner_id(self, rid):
            if rid == runner_id:
                return {"id": 77, "status": "running"}
            return None

        def update_status(self, wf_id, status, error_message=None):
            self.updated.append((wf_id, status, error_message))

    wf_manager = _FakeWfManager()

    def _fake_cleanup(rid, redis_client, reason="process_cleanup"):
        redis_client.set(f"{RUNNER_KEY_PREFIX}:{rid}:status", "stopped")
        redis_client.srem(ACTIVE_RUNNERS_KEY, rid)

    with patch.object(listener_mod, "_cleanup_process_state", side_effect=_fake_cleanup) as mock_cleanup, \
         patch.object(listener_mod, "_pub_and_log"):
        first = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=wf_manager)
        assert first is False
        assert runner_id in state_mod.get_zombie_first_seen()
        assert fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "running"

        state_mod.get_zombie_first_seen()[runner_id] = time.time() - listener_mod.ZOMBIE_GRACE_SECONDS - 1
        second = listener_mod._handle_zombie_heartbeat(runner_id, proc, fr, wf_manager=wf_manager)

    assert second is True
    mock_cleanup.assert_called_once_with(runner_id, fr, reason="zombie_heartbeat_timeout")
    assert fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "stopped"
    assert not fr.sismember(ACTIVE_RUNNERS_KEY, runner_id)
    assert wf_manager.updated, "workflow failed 업데이트가 호출되어야 함"
    assert wf_manager.updated[-1][1] == "failed"
    assert "zombie: subprocess heartbeat timeout" in (wf_manager.updated[-1][2] or "")


# ---------------------------------------------------------------------------
# Phase 3 신규 TC: listener heartbeat 갱신 검증
# ---------------------------------------------------------------------------


def test_listener_renews_heartbeat_for_alive_process(listener_mod, state_mod, fr):
    """RIGHT: PID alive이면 _handle_running_process_heartbeat 호출 시 subprocess_heartbeat 갱신."""
    runner_id = "hb-renew-alive-1"
    proc = MagicMock()
    proc.poll.return_value = None  # alive
    proc.pid = 11001

    state_mod.get_running_processes()[runner_id] = proc
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())
    # 초기에는 heartbeat 없음
    assert fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat") is None

    with patch.object(listener_mod, "_handle_zombie_heartbeat"):
        listener_mod._handle_running_process_heartbeat(runner_id, proc, fr, wf_manager=None)

    hb = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
    assert hb is not None, "_handle_running_process_heartbeat 호출 후 subprocess_heartbeat가 존재해야 함"


def test_listener_heartbeat_uses_correct_ttl(listener_mod, state_mod, fr):
    """CORRECT: heartbeat 갱신 시 TTL이 SUBPROCESS_HEARTBEAT_TTL 이하인지 검증."""
    runner_id = "hb-ttl-check-1"
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 11002

    state_mod.get_running_processes()[runner_id] = proc
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())

    with patch.object(listener_mod, "_handle_zombie_heartbeat"):
        listener_mod._handle_running_process_heartbeat(runner_id, proc, fr, wf_manager=None)

    ttl = fr.ttl(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
    expected_ttl = listener_mod.SUBPROCESS_HEARTBEAT_TTL
    assert 0 < ttl <= expected_ttl, (
        f"TTL {ttl}이 SUBPROCESS_HEARTBEAT_TTL({expected_ttl}) 이하이고 0 초과여야 함"
    )


def test_listener_heartbeat_skips_on_redis_failure(listener_mod, state_mod, fr):
    """ERROR: Redis SET 실패 시 heartbeat 갱신이 조용히 실패하고 zombie 체크는 계속 진행."""
    runner_id = "hb-redis-fail-1"
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 11003

    state_mod.get_running_processes()[runner_id] = proc

    # Redis mock: status get은 성공, set은 실패
    failing_redis = MagicMock()
    failing_redis.get.return_value = "running"
    failing_redis.set.side_effect = Exception("Redis connection error")

    with patch.object(listener_mod, "_handle_zombie_heartbeat") as mock_zombie:
        # Exception이 외부로 전파되지 않아야 함
        result = listener_mod._handle_running_process_heartbeat(runner_id, proc, failing_redis, wf_manager=None)

    assert result == "checked", "Redis 실패해도 함수가 정상 반환해야 함"
    mock_zombie.assert_called_once()  # zombie 체크는 계속 진행


def test_heartbeat_renewed_before_zombie_check(listener_mod, state_mod, fr):
    """BOUNDARY: heartbeat 갱신이 zombie 감지보다 먼저 실행되어 PID alive 러너가 zombie로 판정 안 됨."""
    runner_id = "hb-order-check-1"
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 11004

    state_mod.get_running_processes()[runner_id] = proc
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
    fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", "2026-01-01T00:00:00")
    # subprocess_heartbeat 없는 상태

    # 실제 _handle_zombie_heartbeat를 실행 (mock 없이) — heartbeat 먼저 갱신 후 zombie 체크
    with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
        result = listener_mod._handle_running_process_heartbeat(runner_id, proc, fr, wf_manager=None)

    assert result == "checked"
    # heartbeat가 먼저 갱신되었으므로 zombie_first_seen에 등록되지 않아야 함
    assert runner_id not in state_mod.get_zombie_first_seen(), (
        "heartbeat 갱신이 먼저 실행되어 zombie 오판 없어야 함"
    )
    mock_cleanup.assert_not_called()


def test_initial_heartbeat_uses_shared_ttl():
    """CORRECT: _launch_plan_runner_process 소스에서 SUBPROCESS_HEARTBEAT_TTL 상수 사용 확인."""
    import inspect
    import importlib.util
    from pathlib import Path
    from tests.dev_runner._path_helpers import get_plan_runner_script_path
    script_path = get_plan_runner_script_path()
    spec = importlib.util.spec_from_file_location(
        "_dr_plan_runner_ttl_check", str(script_path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = inspect.getsource(mod._launch_plan_runner_process)
    assert "SUBPROCESS_HEARTBEAT_TTL" in source, (
        "_launch_plan_runner_process가 SUBPROCESS_HEARTBEAT_TTL 상수를 사용해야 함"
    )
    assert "ex=300" not in source, (
        "ex=300 하드코딩이 제거되어야 함"
    )


def test_initial_heartbeat_set_get_consistency(fr):
    """CORRECT: fakeredis에서 SET→GET 순서가 동일 값을 반환하는지 검증."""
    from _dr_constants import RUNNER_KEY_PREFIX, SUBPROCESS_HEARTBEAT_TTL
    runner_id = "hb-setget-1"
    hb_key = f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat"
    hb_val = str(time.time())
    fr.set(hb_key, hb_val, ex=SUBPROCESS_HEARTBEAT_TTL)
    got = fr.get(hb_key)
    assert got is not None, "SET 직후 GET이 None이면 Problem A 재발"
    assert got == hb_val, f"SET({hb_val!r}) != GET({got!r})"


def test_alive_process_never_zombie_even_without_output(listener_mod, state_mod, fr):
    """T3: 무출력 subprocess가 장시간 실행되어도 listener heartbeat 갱신으로 zombie 오판 없음."""
    import subprocess as _sp
    runner_id = "hb-alive-output-1"

    proc = _sp.Popen(
        ["python", "-c", "import time; time.sleep(5)"],
        stdout=_sp.PIPE, stderr=_sp.PIPE,
    )
    try:
        state_mod.get_running_processes()[runner_id] = proc
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time", datetime.now().isoformat())

        with patch.object(listener_mod, "_cleanup_process_state") as mock_cleanup:
            # 3회 heartbeat 갱신 시뮬레이션
            for _ in range(3):
                listener_mod._handle_running_process_heartbeat(runner_id, proc, fr, wf_manager=None)

        hb = fr.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:subprocess_heartbeat")
        assert hb is not None, "subprocess_heartbeat가 존재해야 함"
        assert runner_id not in state_mod.get_zombie_first_seen(), "zombie 오판 없어야 함"
        mock_cleanup.assert_not_called()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

