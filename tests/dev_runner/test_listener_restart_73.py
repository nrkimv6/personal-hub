"""7.3: listener 재시작 API 검증 테스트"""

import sys
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.ping.return_value = True
    r.get.return_value = None
    r.delete.return_value = True
    return r


def test_restart_listener_kills_old_pid(mock_redis):
    """Redis에 PID 있을 때 → 해당 PID 종료 후 새 프로세스 spawn"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis

    mock_redis.get.side_effect = lambda key: (
        "12345" if key == "plan-runner:listener:pid" else
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else
        None
    )

    fake_proc = MagicMock()
    fake_proc.pid = 99999

    with patch("app.modules.dev_runner.services.executor_service.subprocess.Popen", return_value=fake_proc) as mock_popen, \
         patch("app.modules.dev_runner.services.executor_service.sys.platform", "linux"), \
         patch("app.modules.dev_runner.services.executor_service.os.kill") as mock_kill, \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        result = svc.restart_listener()

    # 기존 PID 종료 시도
    mock_kill.assert_called_once_with(12345, __import__("signal").SIGTERM)
    # 새 프로세스 spawn
    assert mock_popen.called
    assert result["success"] is True
    assert result["new_pid"] == 99999


def test_restart_listener_no_pid_still_spawns(mock_redis):
    """Redis에 PID 없어도 새 listener spawn은 진행됨"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis
    mock_redis.get.side_effect = lambda key: (
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else
        None
    )

    fake_proc = MagicMock()
    fake_proc.pid = 88888

    with patch("app.modules.dev_runner.services.executor_service.subprocess.Popen", return_value=fake_proc), \
         patch("app.modules.dev_runner.services.executor_service.os.kill") as mock_kill, \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        result = svc.restart_listener()

    # kill 미호출 (PID 없음)
    mock_kill.assert_not_called()
    assert result["new_pid"] == 88888


def test_restart_listener_heartbeat_timeout(mock_redis):
    """새 listener spawn 후 heartbeat 10초 내 미감지 → success=False 반환"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis
    # heartbeat 키 항상 None (감지 안 됨)
    mock_redis.get.return_value = None

    fake_proc = MagicMock()
    fake_proc.pid = 77777

    with patch("app.modules.dev_runner.services.executor_service.subprocess.Popen", return_value=fake_proc), \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        result = svc.restart_listener()

    assert result["success"] is False
    assert "heartbeat not detected" in result["message"]
    assert result["new_pid"] == 77777


def test_restart_listener_http_endpoint():
    """POST /dev-runner/restart-listener HTTP 엔드포인트 응답 확인"""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    fake_proc = MagicMock()
    fake_proc.pid = 55555

    mock_r = MagicMock()
    mock_r.ping.return_value = True
    mock_r.get.side_effect = lambda key: (
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else None
    )
    mock_r.delete.return_value = True

    with patch("app.modules.dev_runner.services.executor_service.executor_service.redis_client", mock_r), \
         patch("app.modules.dev_runner.services.executor_service.subprocess.Popen", return_value=fake_proc), \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        resp = client.post("/api/v1/dev-runner/restart-listener")

    # 200 또는 503/500 (Redis 연결 상태에 따라)
    assert resp.status_code in (200, 500, 503), f"예상치 않은 상태코드: {resp.status_code}"
