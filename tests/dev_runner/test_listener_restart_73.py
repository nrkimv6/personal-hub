"""7.3: listener 재시작 API 검증 테스트 (Redis 시그널 방식)

수정 이력:
  - 원래 browser_workers.py 직접 subprocess 호출 방식 테스트
  - Redis graceful-exit 시그널 방식으로 전환 후 업데이트
    (SYSTEM 컨텍스트 오염 방지: Session 0 API → Redis → Session 1 watchdog 재시작)
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.modules.dev_runner.services.redis_connection import COMMANDS_KEY


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.ping.return_value = True
    r.get.return_value = None
    r.brpop.return_value = (
        b"result_key",
        json.dumps({"success": True, "message": "graceful-exit acknowledged"}).encode(),
    )
    r.delete.return_value = True
    return r


def test_restart_listener_uses_redis_signal(mock_redis):
    """Redis LPUSH graceful-exit 시그널 전송 확인 (subprocess.run 미호출)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis

    # heartbeat: None → "restarting" → 정상값
    mock_redis.get.side_effect = [
        None,
        b"restarting",
        b"2026-02-25T10:00:00",
    ]

    with patch("subprocess.run") as mock_run, \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]):
        result = svc.restart_listener()

    # subprocess.run이 호출되지 않아야 함 (SYSTEM 컨텍스트 오염 방지)
    assert not mock_run.called, "subprocess.run이 호출됨 — SYSTEM 컨텍스트 오염 위험"

    # Redis LPUSH가 COMMANDS_KEY로 호출되어야 함
    assert mock_redis.lpush.called
    call_args = mock_redis.lpush.call_args
    assert call_args[0][0] == COMMANDS_KEY
    payload = json.loads(call_args[0][1])
    assert payload["action"] == "graceful-exit"

    assert result["success"] is True


def test_restart_listener_heartbeat_not_restarting_timeout(mock_redis):
    """heartbeat가 'restarting'으로 전환되지 않으면 success=False 반환"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis
    # heartbeat 키 항상 None (listener가 시그널 수신 못함)
    mock_redis.get.return_value = None

    with patch("time.sleep"), \
         patch("time.time", side_effect=[0, 5.1, 5.2, 20.3]):
        result = svc.restart_listener()

    assert result["success"] is False
    assert (
        "restarting" in result["message"].lower()
        or "타임아웃" in result["message"]
        or "heartbeat not recovered" in result["message"].lower()
    )


def test_restart_listener_heartbeat_stuck_restarting_timeout(mock_redis):
    """heartbeat가 'restarting'에서 복구되지 않으면 success=False 반환"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis
    # 항상 "restarting" (watchdog가 재시작 못함)
    mock_redis.get.return_value = b"restarting"

    with patch("time.sleep"), \
         patch("time.time", side_effect=[0, 0.1, 0.2,  # 단계 1 통과
                                          0.3, 15.1, 15.2]):  # 단계 2 타임아웃
        result = svc.restart_listener()

    assert result["success"] is False
    assert "15s" in result["message"] or "heartbeat" in result["message"].lower()


def test_restart_listener_http_endpoint():
    """POST /dev-runner/restart-listener HTTP 엔드포인트 응답 확인"""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "app.modules.dev_runner.services.executor_service.ExecutorService.restart_listener",
        return_value={"success": True, "message": "listener restarted"},
    ) as mock_rl:
        resp = client.post("/api/v1/dev-runner/restart-listener")

    assert resp.status_code == 200
    assert mock_rl.called
    data = resp.json()
    assert "success" in data
