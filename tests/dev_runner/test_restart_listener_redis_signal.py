"""
restart-listener Redis 시그널 방식 전환 TC

Phase T1: executor_service.restart_listener() / worker_service.restart_infra("command_listener") /
          dev-runner-command-listener graceful-exit 단위 테스트
Phase T3: graceful-exit 통합 테스트 (fakeredis)
Phase T4: TestClient 기반 E2E 테스트

수정 배경:
  - API(Session 0, SYSTEM) → subprocess.run(browser_workers.py restart-listener)
    → dev-runner-command-listener가 SYSTEM으로 실행 → git dubious ownership 오류
  - 수정: Redis LPUSH("graceful-exit") → Session 1 watchdog가 재시작
"""
import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from tests.dev_runner._path_helpers import load_listener_module

# ─── dev-runner-command-listener 모듈 로드 (하이픈 파일명 → importlib) ───────

_listener_mod = None


def _get_listener_mod():
    global _listener_mod
    if _listener_mod is not None:
        return _listener_mod
    _listener_mod = load_listener_module("dev_runner_command_listener")
    return _listener_mod


# ─── Phase T1: executor_service 단위 테스트 ─────────────────────────────────


class TestExecutorServiceRestartListener:
    """executor_service.restart_listener() — Redis 시그널 방식 검증"""

    @pytest.fixture
    def executor(self):
        """executor_service 인스턴스를 mock redis_client와 함께 생성."""
        from app.modules.dev_runner.services.executor_service import ExecutorService
        svc = ExecutorService.__new__(ExecutorService)
        svc.redis_client = MagicMock()
        svc.redis_client.brpop.return_value = (
            b"result_key",
            json.dumps({"success": True, "message": "graceful-exit acknowledged"}).encode(),
        )
        return svc

    def test_restart_listener_sends_redis_graceful_exit(self, executor):
        """R: restart_listener() 호출 시 redis_client.lpush에 graceful-exit JSON 전송"""
        # heartbeat가 "restarting" → 정상값 순서로 전환되도록 mock
        executor.redis_client.get.side_effect = [
            None,        # 첫 폴링: restarting 아직 없음
            b"restarting",  # 두 번째: restarting 확인
            b"2026-04-10T00:00:00",  # 세 번째: 정상 복구
        ]

        with patch("subprocess.run") as mock_run, \
             patch("time.sleep"):
            result = executor.restart_listener()

        # subprocess.run이 호출되지 않아야 함
        assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 위험"

        # lpush 호출 검증
        assert executor.redis_client.lpush.called
        call_args = executor.redis_client.lpush.call_args
        from app.modules.dev_runner.services.redis_connection import COMMANDS_KEY
        assert call_args[0][0] == COMMANDS_KEY
        payload = json.loads(call_args[0][1])
        assert payload["action"] == "graceful-exit"
        assert payload["source"] == "restart-listener-api"

    def test_restart_listener_waits_heartbeat_restarting_then_recovery(self, executor):
        """R: heartbeat "restarting" 확인 후 정상값 복구 시 success: True 반환"""
        # 단계 1: None → "restarting", 단계 2: "restarting" → 정상값
        executor.redis_client.get.side_effect = [
            None,           # 단계 1 폴링 1: 아직 restarting 아님
            b"restarting",  # 단계 1 폴링 2: restarting 확인
            b"restarting",  # 단계 2 폴링 1: 아직 복구 중
            b"2026-04-10T12:00:00",  # 단계 2 폴링 2: 정상 복구
        ]

        with patch("time.sleep"), patch("time.time") as mock_time:
            # time.time()이 충분히 여유있게 진행되도록 설정
            mock_time.side_effect = [
                0, 0.1, 0.2, 0.3,    # 단계 1 (deadline=5)
                0.4, 0.5, 0.6, 0.7,  # 단계 2 (deadline=15)
                0.8,
            ]
            result = executor.restart_listener()

        assert result["success"] is True
        assert "restarted" in result["message"]

    def test_restart_listener_timeout_no_heartbeat_recovery(self, executor):
        """E: heartbeat가 'restarting'으로 전환되지 않으면 timeout → success: False"""
        # 항상 None 반환 → 5초 타임아웃
        executor.redis_client.get.return_value = None

        with patch("time.sleep"), patch("time.time") as mock_time:
            # 시간이 빠르게 deadline을 넘도록 설정
            mock_time.side_effect = [0, 5.1, 5.2, 20.3]  # 1단계/2단계 deadline 모두 초과
            result = executor.restart_listener()

        assert result["success"] is False
        assert (
            "restarting" in result["message"].lower()
            or "타임아웃" in result["message"]
            or "heartbeat not recovered" in result["message"].lower()
        )

    def test_restart_listener_timeout_stuck_restarting(self, executor):
        """E: heartbeat가 'restarting'에서 정상값으로 복구되지 않으면 success: False"""
        # 단계 1: "restarting" 즉시 확인, 단계 2: 계속 "restarting" 유지
        executor.redis_client.get.return_value = b"restarting"

        with patch("time.sleep"), patch("time.time") as mock_time:
            # 단계 1 deadline(5): 바로 통과, 단계 2 deadline(15): 초과
            mock_time.side_effect = [0, 0.1, 0.2,  # 단계 1
                                     0.3, 15.1, 15.2]  # 단계 2 deadline 초과
            result = executor.restart_listener()

        assert result["success"] is False
        assert "15s" in result["message"] or "heartbeat" in result["message"].lower()


# ─── Phase T1: worker_service 위임 테스트 ────────────────────────────────────


class TestWorkerServiceCommandListenerDelegates:
    """worker_service.restart_infra("command_listener") — executor_service 위임 검증"""

    @pytest.mark.asyncio
    async def test_worker_service_restart_infra_command_listener_delegates(self):
        """R: command_listener 재시작 시 executor_service.restart_listener() 호출, subprocess.run 미호출"""
        from app.modules.system.services.worker_service import WorkerService

        with patch("subprocess.run") as mock_run, \
             patch(
                 "app.modules.system.services.worker_service.executor_service.restart_listener",
                 return_value={"success": True, "message": "listener restarted"},
             ) as mock_rl:
            svc = WorkerService()
            result = await svc.restart_infra("command_listener")

        assert mock_rl.called, "executor_service.restart_listener가 호출되지 않음"
        assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 위험"
        assert result["success"] is True


# ─── Phase T1: graceful-exit 단위 테스트 ────────────────────────────────────


class TestGracefulExitHandler:
    """dev-runner-command-listener._handle_graceful_exit() 단위 테스트"""

    @pytest.fixture(autouse=True)
    def reset_exit_flag(self):
        """각 테스트 전후 _graceful_exit_requested 플래그 초기화"""
        m = _get_listener_mod()
        m._graceful_exit_requested = False
        yield
        m._graceful_exit_requested = False

    @pytest.fixture
    def listener(self):
        return _get_listener_mod()

    @pytest.fixture
    def mock_redis(self):
        r = MagicMock()
        r.set.return_value = True
        return r

    def test_graceful_exit_sets_heartbeat_restarting(self, listener, mock_redis):
        """R: graceful-exit 처리 시 HEARTBEAT_KEY를 'restarting'으로 설정"""
        from _dr_constants import HEARTBEAT_KEY

        result = listener._handle_graceful_exit(mock_redis)

        mock_redis.set.assert_called_once_with(HEARTBEAT_KEY, "restarting", ex=30)

    def test_graceful_exit_sets_global_exit_flag(self, listener, mock_redis):
        """R: graceful-exit 처리 후 _graceful_exit_requested == True"""
        listener._handle_graceful_exit(mock_redis)

        assert listener._graceful_exit_requested is True

    def test_graceful_exit_with_active_runners_warns_not_refuses(self, listener, mock_redis, caplog):
        """B: 활성 runner 존재 시 거부하지 않고 warning 로그 + success: True"""
        # 활성 runner mock (poll() = None → 실행 중)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        listener._running_processes["test-runner-123"] = mock_proc

        try:
            import logging
            with caplog.at_level(logging.WARNING):
                result = listener._handle_graceful_exit(mock_redis)

            assert result["success"] is True, "활성 runner 있어도 graceful-exit 허용해야 함"
            assert any(
                r.levelno >= logging.WARNING and "graceful-exit" in r.getMessage()
                for r in caplog.records
            ), "활성 runner 경고 로그 없음"
        finally:
            listener._running_processes.pop("test-runner-123", None)

    def test_graceful_exit_returns_result_dict(self, listener, mock_redis):
        """R: 반환값이 {"success": True, "message": "graceful-exit scheduled"} 형태"""
        result = listener._handle_graceful_exit(mock_redis)

        assert isinstance(result, dict)
        assert result["success"] is True
        assert "graceful-exit" in result.get("message", "")


# ─── Phase T3: 통합 테스트 (fakeredis) ───────────────────────────────────────


class TestGracefulExitIntegration:
    """graceful-exit → heartbeat 전이 통합 테스트 (fakeredis 사용)"""

    def test_graceful_exit_and_process_lifecycle_integration(self):
        """T3: fakeredis로 전체 흐름 검증.
        ① Redis LPUSH → ② execute_command(graceful-exit) → ③ heartbeat="restarting"
        → ④ _graceful_exit_requested=True
        """
        try:
            import fakeredis
        except ImportError:
            pytest.skip("fakeredis 미설치")

        m = _get_listener_mod()
        from _dr_constants import HEARTBEAT_KEY, COMMANDS_KEY

        # 초기화
        m._graceful_exit_requested = False

        fake_r = fakeredis.FakeRedis()

        # ① Redis LPUSH로 graceful-exit 명령 전송
        command = json.dumps({"action": "graceful-exit", "source": "test", "timestamp": "2026-04-10"})
        fake_r.lpush(COMMANDS_KEY, command)

        # ② BRPOP으로 명령 수신 후 execute_command 실행
        result_raw = fake_r.brpop(COMMANDS_KEY, timeout=1)
        assert result_raw is not None
        _, raw = result_raw
        parsed = json.loads(raw)
        assert parsed["action"] == "graceful-exit"

        command_result = m.execute_command(parsed, fake_r)

        # ③ heartbeat → "restarting"
        hb = fake_r.get(HEARTBEAT_KEY)
        assert hb is not None
        hb_str = hb.decode() if isinstance(hb, bytes) else hb
        assert hb_str == "restarting", f"heartbeat가 'restarting'이 아님: {hb_str!r}"

        # ④ _graceful_exit_requested = True
        assert m._graceful_exit_requested is True

        # 정리
        m._graceful_exit_requested = False


# ─── Phase T4: TestClient E2E ────────────────────────────────────────────────


class TestRestartListenerE2E:
    """TestClient 기반 E2E — API → Redis 경로 검증"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c

    def test_restart_listener_e2e_no_subprocess(self, client):
        """T4: POST /api/v1/dev-runner/restart-listener → subprocess.run 미호출 + Redis LPUSH 호출"""
        from app.modules.dev_runner.services.redis_connection import COMMANDS_KEY

        with patch("subprocess.run") as mock_run, \
             patch(
                 "app.modules.dev_runner.services.executor_service.ExecutorService.restart_listener",
                 return_value={"success": True, "message": "listener restarted"},
             ) as mock_rl:
            resp = client.post("/api/v1/dev-runner/restart-listener")

        assert resp.status_code == 200
        assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 위험"
        assert mock_rl.called, "restart_listener()가 호출되지 않음"

        data = resp.json()
        assert "success" in data

    def test_restart_infra_command_listener_e2e_delegates(self, client):
        """T4: POST /api/v1/system/services/infra/command_listener/restart
        → executor_service.restart_listener 경유 + subprocess.run 미호출
        """
        with patch("subprocess.run") as mock_run, \
             patch(
                 "app.modules.system.services.worker_service.executor_service.restart_listener",
                 return_value={"success": True, "message": "listener restarted"},
             ) as mock_rl:
            resp = client.post("/api/v1/system/services/infra/command_listener/restart")

        assert resp.status_code == 200
        assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 위험"
        assert mock_rl.called, "executor_service.restart_listener가 호출되지 않음"

        data = resp.json()
        assert "success" in data
