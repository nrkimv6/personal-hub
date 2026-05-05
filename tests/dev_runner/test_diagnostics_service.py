"""DiagnosticsService 단위 테스트 (RIGHT-BICEP)"""
import pytest
from unittest.mock import MagicMock

from app.modules.dev_runner.services.diagnostics_service import DiagnosticsService


def _make_svc(**overrides) -> DiagnosticsService:
    svc = DiagnosticsService()
    mock = MagicMock()
    mock.ping = MagicMock()
    mock.info = MagicMock(return_value={"connected_clients": 5})
    mock.get = MagicMock(return_value="1")
    mock.smembers = MagicMock(return_value={"runner1"})
    mock.zrange = MagicMock(return_value=[])
    mock.scan_iter = MagicMock(return_value=[])
    for k, v in overrides.items():
        setattr(mock, k, v)
    svc.redis_client = mock
    return svc


def test_run_diagnostics_right_all_ok(tmp_path):
    """R(Right): 모든 조건 정상 → steps 7개 모두 ok=True."""
    from unittest.mock import patch as _patch
    log_file = tmp_path / "test.log"
    log_file.write_text("log content")

    svc = _make_svc()
    svc.redis_client.get = MagicMock(side_effect=lambda key: {
        "plan-runner:listener:heartbeat": "1",
        "plan-runner:runners:runner1:stream_log_path": str(log_file),
    }.get(key))
    # runner1 status != "running" → has_running=False → pmsg_ok=True (get_pmsg_count 불필요)
    svc.redis_client.hget = MagicMock(return_value=None)

    with _patch(
        "app.modules.dev_runner.services.event_service.get_pmsg_count_last5min",
        return_value=5,
    ):
        result = svc.run_diagnostics()

    steps = result["steps"]

    assert len(steps) == 7
    assert all(s["ok"] for s in steps), [s for s in steps if not s["ok"]]


def test_run_diagnostics_error_redis_down():
    """E(Error): Redis ping 실패 → step1 ok=False, 이후 step 없음."""
    svc = DiagnosticsService()
    svc.redis_client = MagicMock()
    svc.redis_client.ping = MagicMock(side_effect=ConnectionError("down"))

    result = svc.run_diagnostics()
    steps = result["steps"]

    assert len(steps) == 1
    assert steps[0]["ok"] is False
    assert steps[0]["name"] == "Redis 연결"


def test_run_diagnostics_boundary_no_runners():
    """B(Boundary): active runners 없음 → step4 ok=False, step5 ok=False."""
    svc = _make_svc()
    svc.redis_client.smembers = MagicMock(return_value=set())
    svc.redis_client.get = MagicMock(side_effect=lambda key: {
        "plan-runner:listener:heartbeat": "1",
    }.get(key))

    result = svc.run_diagnostics()
    steps = result["steps"]

    step4 = next(s for s in steps if s["step"] == 4)
    step5 = next(s for s in steps if s["step"] == 5)
    assert step4["ok"] is False
    assert step5["ok"] is False


def test_run_diagnostics_boundary_high_connections():
    """B(Boundary): connected_clients=150 → step2 ok=False, "좀비" 포함."""
    svc = _make_svc()
    svc.redis_client.info = MagicMock(return_value={"connected_clients": 150})
    svc.redis_client.get = MagicMock(side_effect=lambda key: {
        "plan-runner:listener:heartbeat": "1",
    }.get(key))

    result = svc.run_diagnostics()
    steps = result["steps"]

    conn_step = next(s for s in steps if s["name"] == "Redis 연결 수")
    assert conn_step["ok"] is False
    assert "좀비" in conn_step["detail"]
