"""tracked_popen TC"""
import subprocess
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_tracked_popen_sync_registers():
    """R: tracked_popen_sync() → Registry에 pid 등록 확인 (mock Registry)"""
    from app.shared.process.tracked_popen import tracked_popen_sync

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.pid = 12345

    mock_register = AsyncMock(return_value=True)

    with patch("subprocess.Popen", return_value=mock_proc), \
         patch("app.shared.process.tracked_popen.ProcessRegistry") as MockRegistry:
        MockRegistry.return_value.register = mock_register
        proc = tracked_popen_sync(["python", "-c", "pass"], role="test")

    assert proc.pid == 12345
    mock_register.assert_called_once()
    call_kwargs = mock_register.call_args
    assert call_kwargs.kwargs.get("role") == "test" or call_kwargs.args[-1] == "test"


@pytest.mark.asyncio
async def test_tracked_popen_sync_redis_fail_still_returns_proc():
    """E: Registry.register 실패 시에도 Popen 객체 정상 반환"""
    from app.shared.process.tracked_popen import tracked_popen_sync

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.pid = 99999

    mock_register = AsyncMock(side_effect=Exception("Redis connection failed"))

    with patch("subprocess.Popen", return_value=mock_proc), \
         patch("app.shared.process.tracked_popen.ProcessRegistry") as MockRegistry:
        MockRegistry.return_value.register = mock_register
        proc = tracked_popen_sync(["echo", "hi"], role="test")

    assert proc.pid == 99999


@pytest.mark.asyncio
async def test_tracked_kill_unregisters_and_kills():
    """R: tracked_kill(pid) → unregister + kill_pid 모두 호출 확인 (mock)"""
    from app.shared.process.tracked_popen import tracked_kill

    mock_unregister = AsyncMock(return_value=True)
    mock_kill = MagicMock(return_value=True)

    with patch("app.shared.process.tracked_popen.ProcessRegistry") as MockRegistry, \
         patch("app.shared.process.tracked_popen.kill_pid", mock_kill):
        MockRegistry.return_value.unregister = mock_unregister
        result = await tracked_kill(1234)

    mock_unregister.assert_called_once_with(1234)
    mock_kill.assert_called_once_with(1234, 5)
    assert result is True
