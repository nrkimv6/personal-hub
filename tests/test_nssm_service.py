"""
NssmService 단위 테스트
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


def test_nssm_service_import():
    """R(Right): NssmService import 성공"""
    from app.modules.system.services.nssm_service import NssmService
    assert NssmService is not None


def test_unregistered_sentinel_shape():
    """R(Right): _unregistered_sentinel 반환 shape 검증"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    result = svc._unregistered_sentinel("test-prefix", "my-project")
    assert result["name"] == "test-prefix"
    assert result["project"] == "my-project"
    assert result["status"] == "Unregistered"
    assert result["start_type"] == "N/A"
    assert "미등록" in result["display_name"]


def test_normalize_status_int():
    """R(Right): 정수 상태 → 문자열 변환"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status(4) == "Running"
    assert svc._normalize_status(1) == "Stopped"
    assert svc._normalize_status(2) == "StartPending"
    assert svc._normalize_status(3) == "StopPending"


def test_normalize_status_boundary():
    """B(Boundary): None, 0, 5 등 매핑 외 값 → 'Unknown'"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status(None) == "Unknown"
    assert svc._normalize_status(0) == "Unknown"
    assert svc._normalize_status(5) == "Unknown"
    assert svc._normalize_status(99) == "Unknown"


def test_normalize_status_string():
    """R(Right): 문자열 상태는 그대로 반환"""
    from app.modules.system.services.nssm_service import NssmService
    svc = NssmService()
    assert svc._normalize_status("Running") == "Running"
    assert svc._normalize_status("Stopped") == "Stopped"


# ── _check_public_frontend_health TC ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_public_frontend_health_right_port_open_returns_healthy(tmp_path):
    """R(Right): 포트 6100 열림 + pid 파일 정상 → frontend_health: healthy"""
    from app.modules.system.services.nssm_service import NssmService

    pid_dir = tmp_path / ".pids"
    pid_dir.mkdir()
    (pid_dir / "frontend.pid").write_text("12345")

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", AsyncMock(return_value=(MagicMock(), mock_writer))):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["frontend_health"] == "healthy"
    assert result["frontend_port"] == 6100
    assert result["frontend_pid"] == 12345
    assert result["degraded_reason"] is None


@pytest.mark.asyncio
async def test_check_public_frontend_health_boundary_port_closed_returns_port_dead(tmp_path):
    """B(Boundary): asyncio.open_connection OSError → degraded_reason: port_dead"""
    from app.modules.system.services.nssm_service import NssmService

    with patch("asyncio.open_connection", AsyncMock(side_effect=OSError("connection refused"))):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["frontend_health"] == "degraded"
    assert result["degraded_reason"] == "port_dead"
    assert result["frontend_pid"] is None


@pytest.mark.asyncio
async def test_check_public_frontend_health_error_pid_file_missing_returns_pid_missing(tmp_path):
    """E(Error): pid 파일 없음 + 포트 열림 → degraded_reason: pid_missing"""
    from app.modules.system.services.nssm_service import NssmService

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", AsyncMock(return_value=(MagicMock(), mock_writer))):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["frontend_health"] == "degraded"
    assert result["degraded_reason"] == "pid_missing"
    assert result["frontend_pid"] is None


@pytest.mark.asyncio
async def test_check_public_frontend_health_boundary_timeout_returns_port_dead(tmp_path):
    """B(Boundary): asyncio.wait_for TimeoutError → degraded_reason: port_dead"""
    from app.modules.system.services.nssm_service import NssmService

    with patch("asyncio.open_connection", AsyncMock(side_effect=asyncio.TimeoutError())):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["frontend_health"] == "degraded"
    assert result["degraded_reason"] == "port_dead"


@pytest.mark.asyncio
async def test_query_services_by_prefix_right_public_gets_health_fields(tmp_path):
    """R(Right): MonitorPage-Public Running 서비스 응답에 frontend_health 포함"""
    import json
    from app.modules.system.services.nssm_service import NssmService

    raw_services = [{"Name": "MonitorPage-Public", "Status": 4, "StartType": 2, "DisplayName": "MonitorPage Public"}]
    mock_stdout = json.dumps(raw_services).encode()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(mock_stdout, b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc), \
         patch("asyncio.wait_for", AsyncMock(return_value=(mock_stdout, b""))), \
         patch.object(NssmService, "_check_public_frontend_health",
                      AsyncMock(return_value={"frontend_health": "healthy", "frontend_port": 6100,
                                              "frontend_pid": 9999, "degraded_reason": None})):
        svc = NssmService()
        # patch wait_for to return directly
        with patch("app.modules.system.services.nssm_service.asyncio.wait_for",
                   AsyncMock(return_value=(mock_stdout, b""))):
            result = await svc._query_services_by_prefix("MonitorPage", "monitor-page")

    assert any(r.get("frontend_health") is not None for r in result), \
        f"MonitorPage-Public 응답에 frontend_health 미포함: {result}"


@pytest.mark.asyncio
async def test_query_services_by_prefix_right_other_service_no_health_fields(tmp_path):
    """R(Right): MonitorPage-Admin 서비스 응답에 frontend_health 미포함"""
    import json
    from app.modules.system.services.nssm_service import NssmService

    raw_services = [{"Name": "MonitorPage-Admin", "Status": 4, "StartType": 2, "DisplayName": "MonitorPage Admin"}]
    mock_stdout = json.dumps(raw_services).encode()

    svc = NssmService()
    with patch("app.modules.system.services.nssm_service.asyncio.wait_for",
               AsyncMock(return_value=(mock_stdout, b""))), \
         patch("app.modules.system.services.nssm_service.asyncio.create_subprocess_shell",
               AsyncMock()):
        result = await svc._query_services_by_prefix("MonitorPage", "monitor-page")

    assert all("frontend_health" not in r for r in result), \
        f"MonitorPage-Admin 응답에 frontend_health 포함됨(기대 안 함): {result}"


# ── T3: 실물 파일시스템 기반 통합 TC ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_public_frontend_health_integration_pid_exists_port_closed(tmp_path):
    """T3: frontend.pid 있음 + 포트 closed → degraded_reason: port_dead (실물 파일시스템)"""
    from app.modules.system.services.nssm_service import NssmService

    pid_dir = tmp_path / ".pids"
    pid_dir.mkdir()
    (pid_dir / "frontend.pid").write_text("55555")

    with patch("asyncio.open_connection", AsyncMock(side_effect=OSError("refused"))):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["degraded_reason"] == "port_dead"


@pytest.mark.asyncio
async def test_check_public_frontend_health_integration_pid_missing_port_open(tmp_path):
    """T3: frontend.pid 없음 + 포트 open → degraded_reason: pid_missing (실물 파일시스템)"""
    from app.modules.system.services.nssm_service import NssmService

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", AsyncMock(return_value=(MagicMock(), mock_writer))):
        result = await NssmService()._check_public_frontend_health(str(tmp_path))

    assert result["degraded_reason"] == "pid_missing"
