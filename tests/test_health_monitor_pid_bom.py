"""
health_monitor_service PID BOM 처리 단위 테스트

Phase T1: 단위 테스트
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.health_monitor_service import HealthMonitorService


class TestHealthMonitorReadPidFile:
    """HealthMonitorService.read_pid_file BOM 처리 단위 테스트"""

    def _make_service(self, pid_dir: Path):
        svc = HealthMonitorService.__new__(HealthMonitorService)
        svc.pid_dir = pid_dir
        return svc

    def test_read_pid_bom(self, tmp_path):
        """R(Right): BOM 포함 PID 파일 → 정수 반환"""
        pid_file = tmp_path / "my_service.pid"
        pid_file.write_bytes(b'\xef\xbb\xbf4321\n')

        svc = self._make_service(tmp_path)
        config = {"pid_file": "my_service.pid"}

        with patch('app.services.health_monitor_service.SERVICE_CONFIG', {"my_service": config}):
            result = svc.read_pid_file("my_service")

        assert result == 4321

    def test_read_pid_normal(self, tmp_path):
        """R(Right): 정상 PID 파일 (BOM 없음) → 정수 반환"""
        pid_file = tmp_path / "my_service.pid"
        pid_file.write_text("8765\n", encoding='ascii')

        svc = self._make_service(tmp_path)
        config = {"pid_file": "my_service.pid"}

        with patch('app.services.health_monitor_service.SERVICE_CONFIG', {"my_service": config}):
            result = svc.read_pid_file("my_service")

        assert result == 8765

    def test_read_pid_missing(self, tmp_path):
        """B(Boundary): 파일 없음 → None 반환"""
        svc = self._make_service(tmp_path)
        config = {"pid_file": "nonexistent.pid"}

        with patch('app.services.health_monitor_service.SERVICE_CONFIG', {"my_service": config}):
            result = svc.read_pid_file("my_service")

        assert result is None


class TestHealthMonitorReadPidFileIntegration:
    """HealthMonitorService.read_pid_file T3: 실제 파일 I/O 통합 테스트"""

    def test_read_pid_bom_real(self, tmp_path):
        """T3: 실제 tmp BOM PID 파일 → read_pid_file → 정수 반환"""
        pid_file = tmp_path / "test_svc.pid"
        pid_file.write_bytes(b'\xef\xbb\xbf2468\r\n')

        svc = HealthMonitorService.__new__(HealthMonitorService)
        svc.pid_dir = tmp_path

        config = {"pid_file": "test_svc.pid"}

        with patch('app.services.health_monitor_service.SERVICE_CONFIG', {"test_svc": config}):
            result = svc.read_pid_file("test_svc")

        assert result == 2468, f"BOM PID 파싱 실패: result={result}"
