"""
Tests for SystemService NSSM unregistered sentinel logic
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.modules.system.services.nssm_service import NssmService


@pytest.fixture
def svc():
    return NssmService()


# === _unregistered_sentinel ===

def test_unregistered_sentinel_returns_correct_shape(svc):
    """R: 5개 키 모두 존재 + status=="Unregistered" + display_name에 "미등록" 포함"""
    result = svc._unregistered_sentinel("SleepNow", "sleep-now")
    assert set(result.keys()) == {"name", "project", "status", "start_type", "display_name"}
    assert result["status"] == "Unregistered"
    assert "미등록" in result["display_name"]
    assert result["start_type"] == "N/A"


def test_unregistered_sentinel_name_embedded(svc):
    """R: name 파라미터가 반환 dict의 name 필드에 그대로 반영"""
    result = svc._unregistered_sentinel("MyService", "my-project")
    assert result["name"] == "MyService"
    assert result["project"] == "my-project"


# === _query_services_by_prefix ===

@pytest.mark.asyncio
async def test_query_services_by_prefix_empty_stdout_returns_sentinel(svc):
    """E: stdout 빈 문자열 → 리스트 1건, status=="Unregistered" """
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_proc), \
         patch("asyncio.wait_for", AsyncMock(return_value=(b"", b""))):
        result = await svc._query_services_by_prefix("SleepNow", "sleep-now")

    assert len(result) == 1
    assert result[0]["status"] == "Unregistered"
    assert result[0]["name"] == "SleepNow"


@pytest.mark.asyncio
async def test_query_services_by_prefix_json_error_returns_sentinel(svc):
    """E: stdout 비JSON → sentinel 반환"""
    with patch("asyncio.create_subprocess_shell"), \
         patch("asyncio.wait_for", AsyncMock(return_value=(b"not-json", b""))):
        result = await svc._query_services_by_prefix("SleepNow", "sleep-now")

    assert len(result) == 1
    assert result[0]["status"] == "Unregistered"


@pytest.mark.asyncio
async def test_query_services_by_prefix_empty_array_returns_sentinel(svc):
    """B: PowerShell이 [] 반환 → sentinel 반환"""
    with patch("asyncio.create_subprocess_shell"), \
         patch("asyncio.wait_for", AsyncMock(return_value=(b"[]", b""))):
        result = await svc._query_services_by_prefix("SleepNow", "sleep-now")

    assert len(result) == 1
    assert result[0]["status"] == "Unregistered"


@pytest.mark.asyncio
async def test_query_services_by_prefix_normal_returns_services(svc):
    """R: 정상 서비스 1건 → sentinel 아닌 실제 서비스 반환"""
    import json
    svc_data = [{"Name": "SleepNow_api", "Status": 4, "StartType": 2, "DisplayName": "SleepNow API"}]
    payload = json.dumps(svc_data).encode()

    with patch("asyncio.create_subprocess_shell"), \
         patch("asyncio.wait_for", AsyncMock(return_value=(payload, b""))):
        result = await svc._query_services_by_prefix("SleepNow", "sleep-now")

    assert len(result) == 1
    assert result[0]["status"] == "Running"
    assert result[0]["name"] == "SleepNow_api"


# === _query_service_by_name ===

@pytest.mark.asyncio
async def test_query_service_by_name_empty_stdout_returns_sentinel(svc):
    """E: stdout 빈 → sentinel 반환"""
    with patch("asyncio.create_subprocess_shell"), \
         patch("asyncio.wait_for", AsyncMock(return_value=(b"", b""))):
        result = await svc._query_service_by_name("SleepNow_api", "sleep-now")

    assert result["status"] == "Unregistered"
    assert result["name"] == "SleepNow_api"


@pytest.mark.asyncio
async def test_query_service_by_name_normal_returns_service(svc):
    """R: 정상 → 실제 서비스 dict 반환"""
    import json
    svc_data = {"Name": "SleepNow_api", "Status": 4, "StartType": 2, "DisplayName": "SleepNow API"}
    payload = json.dumps(svc_data).encode()

    with patch("asyncio.create_subprocess_shell"), \
         patch("asyncio.wait_for", AsyncMock(return_value=(payload, b""))):
        result = await svc._query_service_by_name("SleepNow_api", "sleep-now")

    assert result["status"] == "Running"
    assert result["name"] == "SleepNow_api"
