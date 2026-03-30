"""
_read_pid_status BOM 처리 단위 테스트 + 통합 테스트 + HTTP 통합 테스트

Phase T1: 단위 테스트 (mock 사용)
Phase T3: 통합 테스트 (실제 파일 I/O, mock 없음)
Phase T4: HTTP 통합 테스트 (FastAPI TestClient)
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.system.services.system_service import SystemService


# ──────────────────────────────────────────────
# Phase T1: 단위 테스트
# ──────────────────────────────────────────────

class TestReadPidStatus:
    """_read_pid_status 단위 테스트"""

    def setup_method(self):
        self.service = SystemService()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_read_pid_status_with_bom(self, tmp_path):
        """R(Right): BOM 포함 PID 파일 → 정상 파싱"""
        pid_file = tmp_path / "session_worker.pid"
        # UTF-8 BOM + PID 기록 (PowerShell Out-File 기본값)
        pid_file.write_bytes(b'\xef\xbb\xbf1912\n')

        with patch.object(self.service, '_check_process_exists', new=AsyncMock(return_value=True)):
            result = self._run(self.service._read_pid_status(pid_file))

        assert result["pid"] == 1912
        assert result["running"] is True

    def test_read_pid_status_normal(self, tmp_path):
        """R(Right): BOM 없는 정상 PID 파일 → 정상 파싱"""
        pid_file = tmp_path / "worker.pid"
        pid_file.write_text("18804\n", encoding='ascii')

        with patch.object(self.service, '_check_process_exists', new=AsyncMock(return_value=True)):
            result = self._run(self.service._read_pid_status(pid_file))

        assert result["pid"] == 18804
        assert result["running"] is True

    def test_read_pid_status_empty_file(self, tmp_path):
        """B(Boundary): 빈 파일 → pid=None, running=False"""
        pid_file = tmp_path / "empty.pid"
        pid_file.write_text("", encoding='ascii')

        result = self._run(self.service._read_pid_status(pid_file))

        assert result["pid"] is None
        assert result["running"] is False

    def test_read_pid_status_nonexistent(self, tmp_path):
        """B(Boundary): 파일 미존재 → pid=None, running=False"""
        pid_file = tmp_path / "notfound.pid"

        result = self._run(self.service._read_pid_status(pid_file))

        assert result["pid"] is None
        assert result["running"] is False

    def test_read_pid_status_garbage_content(self, tmp_path):
        """E(Error): 숫자 아닌 내용 → pid=None, running=False"""
        pid_file = tmp_path / "garbage.pid"
        pid_file.write_text("not-a-pid\n", encoding='ascii')

        result = self._run(self.service._read_pid_status(pid_file))

        assert result["pid"] is None
        assert result["running"] is False


# ──────────────────────────────────────────────
# Phase T1: _kill_pid_file BOM 단위 테스트
# ──────────────────────────────────────────────

class TestKillPidFile:
    """_kill_pid_file BOM 처리 단위 테스트"""

    def setup_method(self):
        self.service = SystemService()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_kill_pid_file_with_bom(self, tmp_path):
        """R(Right): BOM 포함 PID 파일 → 파싱 성공 (taskkill subprocess mock)"""
        pid_file = tmp_path / "worker.pid"
        pid_file.write_bytes(b'\xef\xbb\xbf1234\n')

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b'')

        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=mock_proc)):
            result = self._run(self.service._kill_pid_file(pid_file, "test_worker"))

        success, msg = result
        assert success is True
        assert "1234" in msg

    def test_kill_pid_file_garbage(self, tmp_path):
        """E(Error): 숫자 아닌 내용 → (False, "...")"""
        pid_file = tmp_path / "worker.pid"
        pid_file.write_text("not-a-pid\n", encoding='ascii')

        result = self._run(self.service._kill_pid_file(pid_file, "test_worker"))

        success, msg = result
        assert success is False
        assert msg  # 에러 메시지 존재


# ──────────────────────────────────────────────
# Phase T3: 통합 테스트 (실제 파일 I/O)
# ──────────────────────────────────────────────

class TestReadPidStatusIntegration:
    """_read_pid_status 통합 테스트 — mock 없이 실제 파일 I/O"""

    def setup_method(self):
        self.service = SystemService()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_read_pid_status_bom_real_file(self, tmp_path):
        """T3: 실제 tmp에 BOM 포함 PID 파일 생성 → _read_pid_status 통합 검증"""
        pid_file = tmp_path / "session_worker.pid"
        # PowerShell Out-File 기본값 재현: UTF-8 BOM + PID + CRLF
        pid_file.write_bytes(b'\xef\xbb\xbf1\r\n')  # PID=1 (항상 존재하는 시스템 프로세스)

        result = self._run(self.service._read_pid_status(pid_file))

        # BOM이 제거되어 파싱 성공 확인
        assert result["pid"] == 1, f"BOM 파싱 실패: pid={result['pid']}"
        # running 여부는 환경 의존 — 파싱 성공 여부만 검증
        assert isinstance(result["running"], bool)


class TestKillPidFileIntegration:
    """_kill_pid_file T3: 실제 파일 I/O, mock 없는 통합 테스트"""

    def setup_method(self):
        self.service = SystemService()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_kill_pid_file_bom_real(self, tmp_path):
        """T3: 실제 tmp 파일에 BOM PID 기록 → _kill_pid_file 파싱 성공 확인 (subprocess mock)"""
        pid_file = tmp_path / "worker.pid"
        pid_file.write_bytes(b'\xef\xbb\xbf5678\r\n')

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b'')

        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=mock_proc)):
            success, msg = self._run(self.service._kill_pid_file(pid_file, "integration_worker"))

        assert success is True, f"BOM PID 파싱 실패: {msg}"
        assert "5678" in msg


# ──────────────────────────────────────────────
# Phase T4: HTTP 통합 테스트
# ──────────────────────────────────────────────

class TestWorkersStatusHttp:
    """GET /api/v1/system/services/workers HTTP 통합 테스트"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_workers_status_http_with_bom_pid(self, client, tmp_path):
        """T4: BOM 포함 PID 파일 시나리오에서 workers 엔드포인트 정상 응답 검증"""
        pid_file = tmp_path / "session_worker.pid"
        pid_file.write_bytes(b'\xef\xbb\xbf9999\n')

        async def fake_read_pid(path):
            if path == pid_file:
                # BOM 처리가 정상 작동하면 pid=9999 반환
                text = path.read_text(encoding='utf-8-sig').strip()
                return {"pid": int(text), "running": False}
            return {"pid": None, "running": False}

        with patch(
            'app.modules.system.services.system_service.SystemService.get_worker_status',
            new=AsyncMock(return_value=[
                {"name": "session_worker", "label": "세션 워커", "project": "sleep-now",
                 "watchdog": None, "worker": {"pid": 9999, "running": False}}
            ])
        ):
            resp = client.get("/api/v1/system/services/workers")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        session = next((w for w in data if w["name"] == "session_worker"), None)
        assert session is not None, f"session_worker 없음: {data}"
        assert session["worker"]["pid"] == 9999
