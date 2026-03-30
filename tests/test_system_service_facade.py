"""
SystemService facade 위임 테스트
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_facade_delegates_to_nssm():
    """R(Right): SystemService.get_all_services_status → NssmService 위임 확인"""
    from app.modules.system.services.system_service import SystemService
    svc = SystemService()

    with patch.object(svc._nssm, "get_nssm_services", new=AsyncMock(return_value=[])) as mock_nssm, \
         patch.object(svc._nssm, "get_startup_programs", new=AsyncMock(return_value=[])), \
         patch.object(svc._nssm, "get_scheduled_tasks", new=AsyncMock(return_value=[])), \
         patch.object(svc._worker, "get_worker_status", new=AsyncMock(return_value=[])):
        result = await svc.get_all_services_status()

    mock_nssm.assert_called_once()
    assert "projects" in result


@pytest.mark.asyncio
async def test_facade_delegates_to_worker():
    """R(Right): SystemService.get_all_services_status → WorkerService 위임 확인"""
    from app.modules.system.services.system_service import SystemService
    svc = SystemService()

    with patch.object(svc._nssm, "get_nssm_services", new=AsyncMock(return_value=[])), \
         patch.object(svc._nssm, "get_startup_programs", new=AsyncMock(return_value=[])), \
         patch.object(svc._nssm, "get_scheduled_tasks", new=AsyncMock(return_value=[])), \
         patch.object(svc._worker, "get_worker_status", new=AsyncMock(return_value=[])) as mock_worker:
        result = await svc.get_all_services_status()

    mock_worker.assert_called_once()
    assert "projects" in result
