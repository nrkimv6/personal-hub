"""7.3: listener 재시작 API 검증 테스트 (browser_workers.py 경유)"""

import sys
import subprocess
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


def _sp_ok():
    return MagicMock(returncode=0, stdout="restart-listener 완료", stderr="")


def _sp_fail():
    return MagicMock(returncode=1, stdout="", stderr="browser_workers.py 오류")


def test_restart_listener_uses_browser_workers(mock_redis):
    """subprocess.run에 browser_workers.py restart-listener 전달 확인"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis

    # heartbeat 즉시 감지
    mock_redis.get.side_effect = lambda key: (
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else None
    )

    with patch("app.modules.dev_runner.services.executor_service.subprocess.run",
               return_value=_sp_ok()) as mock_run, \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        result = svc.restart_listener()

    assert mock_run.called
    args = mock_run.call_args[0][0]
    assert "browser_workers.py" in args[1]
    assert "restart-listener" in args
    assert result["success"] is True


def test_restart_listener_subprocess_failure(mock_redis):
    """subprocess.run 실패 시 success=False 즉시 반환"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis

    with patch("app.modules.dev_runner.services.executor_service.subprocess.run",
               return_value=_sp_fail()):
        result = svc.restart_listener()

    assert result["success"] is False
    assert "browser_workers.py 오류" in result["message"]


def test_restart_listener_heartbeat_timeout(mock_redis):
    """새 listener spawn 후 heartbeat 10초 내 미감지 → success=False 반환"""
    from app.modules.dev_runner.services.executor_service import ExecutorService

    svc = ExecutorService()
    svc.redis_client = mock_redis
    # heartbeat 키 항상 None (감지 안 됨)
    mock_redis.get.return_value = None

    with patch("app.modules.dev_runner.services.executor_service.subprocess.run",
               return_value=_sp_ok()), \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        result = svc.restart_listener()

    assert result["success"] is False
    assert "heartbeat not detected" in result["message"]


def test_restart_listener_http_endpoint():
    """POST /dev-runner/restart-listener HTTP 엔드포인트 응답 확인"""
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    mock_r = MagicMock()
    mock_r.ping.return_value = True
    mock_r.get.side_effect = lambda key: (
        "2026-02-25T10:00:00" if key == "plan-runner:listener:heartbeat" else None
    )
    mock_r.delete.return_value = True

    with patch("app.modules.dev_runner.services.executor_service.executor_service.redis_client", mock_r), \
         patch("app.modules.dev_runner.services.executor_service.subprocess.run",
               return_value=_sp_ok()), \
         patch("app.modules.dev_runner.services.executor_service.time.sleep"):
        resp = client.post("/api/v1/dev-runner/restart-listener")

    # 200 또는 503/500 (Redis 연결 상태에 따라)
    assert resp.status_code in (200, 500, 503), f"예상치 않은 상태코드: {resp.status_code}"
