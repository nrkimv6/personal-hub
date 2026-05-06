"""heartbeat 머지 보호 조건 및 _monitor_pid_until_exit reason TC

대상 소스: scripts/dev-runner-command-listener.py
수정 내용:
  - heartbeat L2576: MERGE_ACTIVE_STATUSES 상수 사용 (하드코딩 3개 → 전체 커버)
  - _monitor_pid_until_exit L334: reason="heartbeat_pid_exit" (보호 가드 인식)
  - heartbeat L2582: 로그에 merge_status 포함
"""

import importlib.util
import pytest
from unittest.mock import MagicMock, patch, call
import fakeredis

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing


# ========== 모듈 로드 ==========

_listener_mod = None


def _get_listener():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_command_listener", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _listener_mod = mod
    return mod


@pytest.fixture(scope="module")
def listener_mod():
    return _get_listener()


@pytest.fixture(scope="module")
def process_utils_mod(listener_mod):
    import sys

    return sys.modules["_dr_process_utils"]


@pytest.fixture
def fr():
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


RUNNER_KEY_PREFIX = "plan-runner:runners"


# ========== Phase T1-1: heartbeat 보호 조건 TC ==========


class TestHeartbeatMergeGuard:
    """heartbeat 루프의 머지 진행 중 cleanup 스킵 조건 검증.

    수정 전: `if _hb_mr or _hb_ms in ("queued", "merging", "pending_merge")`
    수정 후: `if _hb_mr or _hb_ms in MERGE_ACTIVE_STATUSES`

    MERGE_ACTIVE_STATUSES = ("pre_merge", "queued", "merging", "pending_merge",
                              "resolving", "testing", "fixing")
    """

    def _setup_runner(self, mod, fr, runner_id: str, merge_status=None, merge_requested=None):
        """fakeredis에 runner 상태 설정"""
        if merge_status:
            fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", merge_status)
        if merge_requested:
            fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_requested", merge_requested)

    def _call_cleanup_state_guarded(self, mod, fr, runner_id: str):
        """heartbeat_dead_process reason으로 _cleanup_process_state 호출 — 보호 가드 적용됨"""
        mod._cleanup_process_state(runner_id, fr, reason="heartbeat_dead_process")

    def test_heartbeat_skips_cleanup_pre_merge_right(self, listener_mod, fr):
        """R: merge_status="pre_merge" + merge_requested 없음 → cleanup 거부

        heartbeat_dead_process reason은 보호 가드(L163)를 통해 MERGE_ACTIVE_STATUSES 체크.
        수정 전이라면 "pre_merge"가 하드코딩에 없어 cleanup이 실행됨.
        """
        runner_id = "test-pre-merge"
        self._setup_runner(listener_mod, fr, runner_id, merge_status="pre_merge")

        # _running_processes에 등록하여 cleanup이 실제로 진행을 시도하게 함
        mock_proc = MagicMock()
        listener_mod._running_processes[runner_id] = mock_proc

        try:
            # WorktreeManager.remove patch — 실제 파일시스템 건드리지 않기 위해
            with patch.object(listener_mod, "WorktreeManager") as mock_wm:
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            # 보호 가드에 의해 cleanup 거부 → _running_processes에서 제거되지 않아야 함
            assert runner_id in listener_mod._running_processes, (
                "merge_status='pre_merge'이면 heartbeat cleanup이 거부되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_heartbeat_skips_cleanup_resolving_right(self, listener_mod, fr):
        """R: merge_status="resolving" → cleanup 거부 (MERGE_ACTIVE_STATUSES 포함)"""
        runner_id = "test-resolving"
        self._setup_runner(listener_mod, fr, runner_id, merge_status="resolving")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            assert runner_id in listener_mod._running_processes, (
                "merge_status='resolving'이면 heartbeat cleanup이 거부되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_heartbeat_skips_cleanup_testing_right(self, listener_mod, fr):
        """R: merge_status="testing" → cleanup 거부 (MERGE_ACTIVE_STATUSES 포함)"""
        runner_id = "test-testing"
        self._setup_runner(listener_mod, fr, runner_id, merge_status="testing")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            assert runner_id in listener_mod._running_processes, (
                "merge_status='testing'이면 heartbeat cleanup이 거부되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_heartbeat_skips_cleanup_fixing_right(self, listener_mod, fr):
        """R: merge_status="fixing" → cleanup 거부 (MERGE_ACTIVE_STATUSES 포함)"""
        runner_id = "test-fixing"
        self._setup_runner(listener_mod, fr, runner_id, merge_status="fixing")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            assert runner_id in listener_mod._running_processes, (
                "merge_status='fixing'이면 heartbeat cleanup이 거부되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_heartbeat_cleanup_no_merge_signal_right(self, listener_mod, fr):
        """R: merge_status=None + merge_requested=None → cleanup 진행됨 (기존 동작 보존)"""
        runner_id = "test-no-signal"
        # merge 관련 키 없음
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            # merge 시그널 없으면 cleanup이 진행 → _running_processes에서 제거
            assert runner_id not in listener_mod._running_processes, (
                "merge 시그널 없으면 heartbeat cleanup이 진행되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_heartbeat_cleanup_stopped_status_boundary(self, listener_mod, fr):
        """B: merge_status="stopped" → cleanup 진행됨 (MERGE_ACTIVE_STATUSES 미포함)"""
        runner_id = "test-stopped"
        self._setup_runner(listener_mod, fr, runner_id, merge_status="stopped")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                self._call_cleanup_state_guarded(listener_mod, fr, runner_id)

            assert runner_id not in listener_mod._running_processes, (
                "merge_status='stopped'은 MERGE_ACTIVE_STATUSES 미포함, cleanup이 진행되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)


# ========== Phase T1-2: _monitor_pid_until_exit reason TC ==========


class TestMonitorPidExitReason:
    """_monitor_pid_until_exit가 heartbeat_ prefix reason으로 cleanup 호출하는지 검증"""

    def test_monitor_pid_exit_reason_has_heartbeat_prefix_right(self, listener_mod, process_utils_mod, fr):
        """R: _monitor_pid_until_exit → reason="heartbeat_pid_exit" 로 cleanup 호출

        수정 전: reason="pid_exit_detected" → 보호 가드 우회
        수정 후: reason="heartbeat_pid_exit" → 보호 가드 인식 가능
        """
        runner_id = "test-monitor-pid"
        pid = 99999

        # _is_pid_alive: 첫 번째 True(alive), 두 번째 False(종료)로 시뮬레이션
        call_count = {"n": 0}

        def fake_is_pid_alive(p):
            call_count["n"] += 1
            return call_count["n"] < 2  # 두 번째 호출부터 False

        listener_mod._running_processes[runner_id] = MagicMock()

        captured_reason = {}

        def fake_cleanup(rid, redis_client, reason="process_cleanup"):
            captured_reason["reason"] = reason
            listener_mod._running_processes.pop(rid, None)

        import threading
        with patch.object(process_utils_mod, "_is_pid_alive", side_effect=fake_is_pid_alive), \
             patch.object(process_utils_mod, "_cleanup_process_state", side_effect=fake_cleanup):
            t = threading.Thread(
                target=listener_mod._monitor_pid_until_exit,
                args=(runner_id, pid, fr),
                daemon=True,
            )
            t.start()
            t.join(timeout=5)

        assert "reason" in captured_reason, "_cleanup_process_state가 호출되지 않음"
        assert captured_reason["reason"] == "heartbeat_pid_exit", (
            f"reason이 'heartbeat_pid_exit'이어야 하는데 '{captured_reason['reason']}'임"
        )

    def test_cleanup_guard_blocks_heartbeat_pid_exit_right(self, listener_mod, fr):
        """R: reason="heartbeat_pid_exit" + merge_status="pre_merge" → 보호 가드에 의해 cleanup 거부

        _cleanup_process_state의 L163 보호 가드:
          if reason.startswith(("reconnect_", "heartbeat_")): → MERGE_ACTIVE_STATUSES 체크
        """
        runner_id = "test-guard-heartbeat-pid"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "pre_merge")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                listener_mod._cleanup_process_state(
                    runner_id, fr, reason="heartbeat_pid_exit"
                )

            # 보호 가드에 의해 cleanup 거부 → _running_processes에서 제거되지 않아야 함
            assert runner_id in listener_mod._running_processes, (
                "reason='heartbeat_pid_exit' + merge_status='pre_merge'이면 "
                "보호 가드에 의해 cleanup이 거부되어야 함"
            )
        finally:
            listener_mod._running_processes.pop(runner_id, None)


# ========== Phase T2: Claim Heartbeat 갱신 TC ==========


class TestListenerClaimHeartbeat:
    """_handle_running_process_heartbeat 내 claim heartbeat 갱신 경로를 검증.

    listener heartbeat 루프에서 plan_file에 연결된 active claim의 heartbeat_at이 갱신되는지
    mock DB 조합으로 확인한다.
    """

    def test_R_claim_heartbeat_called_for_active_claim(self, listener_mod, fr):
        """R: plan_file이 Redis에 있고 active claim 존재 → heartbeat_claim 호출됨"""
        runner_id = "test-claim-hb-r1"
        plan_file = "docs/plan/test-claim.md"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # 프로세스 살아있음
        listener_mod._running_processes[runner_id] = mock_proc

        mock_db = MagicMock()
        mock_claim = MagicMock()
        mock_claim.claim_id = "claim-hb-001"
        mock_claim.state = "active"
        mock_hb_fn = MagicMock()
        mock_get_fn = MagicMock(return_value=mock_claim)

        try:
            with patch("app.database.SessionLocal", return_value=mock_db), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.get_active_claim_for_plan",
                     mock_get_fn,
                 ), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.heartbeat_claim",
                     mock_hb_fn,
                 ), \
                 patch.object(listener_mod, "_handle_zombie_heartbeat"):
                listener_mod._handle_running_process_heartbeat(runner_id, mock_proc, fr)

            mock_hb_fn.assert_called_once_with(mock_db, "claim-hb-001")
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_B_no_claim_when_plan_file_missing(self, listener_mod, fr):
        """B: plan_file이 Redis에 없으면 claim heartbeat를 호출하지 않는다"""
        runner_id = "test-claim-hb-b1"
        # plan_file 키 미설정

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        listener_mod._running_processes[runner_id] = mock_proc
        mock_hb_fn = MagicMock()

        try:
            with patch(
                "app.modules.dev_runner.services.plan_execution_claim_service.heartbeat_claim",
                mock_hb_fn,
            ), \
                patch.object(listener_mod, "_handle_zombie_heartbeat"):
                listener_mod._handle_running_process_heartbeat(runner_id, mock_proc, fr)

            mock_hb_fn.assert_not_called()
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_B_no_heartbeat_for_queued_claim(self, listener_mod, fr):
        """B: plan_file이 있고 claim은 queued 상태 → heartbeat_claim 호출 안 함"""
        runner_id = "test-claim-hb-b2"
        plan_file = "docs/plan/queued-plan.md"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        listener_mod._running_processes[runner_id] = mock_proc

        mock_db = MagicMock()
        mock_claim = MagicMock()
        mock_claim.claim_id = "claim-queued-001"
        mock_claim.state = "queued"  # queued 상태
        mock_hb_fn = MagicMock()
        mock_get_fn = MagicMock(return_value=mock_claim)

        try:
            with patch("app.database.SessionLocal", return_value=mock_db), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.get_active_claim_for_plan",
                     mock_get_fn,
                 ), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.heartbeat_claim",
                     mock_hb_fn,
                 ), \
                 patch.object(listener_mod, "_handle_zombie_heartbeat"):
                listener_mod._handle_running_process_heartbeat(runner_id, mock_proc, fr)

            # queued 상태이면 heartbeat_claim을 호출하지 않는다
            mock_hb_fn.assert_not_called()
        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_E_claim_heartbeat_error_is_swallowed(self, listener_mod, fr):
        """E: heartbeat_claim 내부에서 예외 발생 → 무시되고 정상 진행된다"""
        runner_id = "test-claim-hb-e1"
        plan_file = "docs/plan/error-plan.md"
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", plan_file)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        listener_mod._running_processes[runner_id] = mock_proc

        mock_db = MagicMock()
        mock_claim = MagicMock()
        mock_claim.claim_id = "claim-err-001"
        mock_claim.state = "active"
        mock_get_fn = MagicMock(return_value=mock_claim)
        mock_hb_fn = MagicMock(side_effect=Exception("DB error"))

        try:
            with patch("app.database.SessionLocal", return_value=mock_db), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.get_active_claim_for_plan",
                     mock_get_fn,
                 ), \
                 patch(
                     "app.modules.dev_runner.services.plan_execution_claim_service.heartbeat_claim",
                     mock_hb_fn,
                 ), \
                 patch.object(listener_mod, "_handle_zombie_heartbeat"):
                # 예외가 전파되지 않아야 한다
                result = listener_mod._handle_running_process_heartbeat(runner_id, mock_proc, fr)

            # 함수가 정상 반환값을 돌려줬는지 확인 ("checked")
            assert result == "checked"
        finally:
            listener_mod._running_processes.pop(runner_id, None)
