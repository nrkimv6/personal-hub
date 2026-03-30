"""
WorkerService 단위 테스트
"""
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


def test_worker_service_import():
    """R(Right): WorkerService import 성공"""
    from app.modules.system.services.worker_service import WorkerService
    assert WorkerService is not None


@pytest.mark.asyncio
async def test_read_pid_status_bom(tmp_path):
    """R(Right): BOM PID 파일 → 정상 파싱"""
    from app.modules.system.services.worker_service import WorkerService
    pid_file = tmp_path / "test.pid"
    # UTF-8 BOM + PID
    pid_file.write_bytes(b"\xef\xbb\xbf12345\n")

    svc = WorkerService()
    with patch.object(svc, "_check_process_exists", new=AsyncMock(return_value=True)):
        result = await svc._read_pid_status(pid_file)

    assert result["pid"] == 12345
    assert result["running"] is True


@pytest.mark.asyncio
async def test_read_pid_status_missing_file(tmp_path):
    """B(Boundary): PID 파일 없음 → pid=None, running=False"""
    from app.modules.system.services.worker_service import WorkerService
    svc = WorkerService()
    result = await svc._read_pid_status(tmp_path / "nonexistent.pid")
    assert result["pid"] is None
    assert result["running"] is False


@pytest.mark.asyncio
async def test_kill_pid_file_missing():
    """B(Boundary): PID 파일 없음 → (False, 'PID 파일 없음')"""
    from app.modules.system.services.worker_service import WorkerService
    svc = WorkerService()
    success, msg = await svc._kill_pid_file(Path("/nonexistent/path.pid"), "test-label")
    assert success is False
    assert "PID 파일 없음" in msg


@pytest.mark.asyncio
async def test_read_pid_status_invalid_content(tmp_path):
    """E(Error): PID 파일 내용이 숫자가 아닐 때 → pid=None, running=False"""
    from app.modules.system.services.worker_service import WorkerService
    pid_file = tmp_path / "bad.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")
    svc = WorkerService()
    result = await svc._read_pid_status(pid_file)
    assert result["pid"] is None
    assert result["running"] is False
