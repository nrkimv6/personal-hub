"""
tests/test_wmi_healthcheck.py — WMI 헬스체크 단위 테스트
"""
import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

# scripts 디렉토리를 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from browser_workers import BrowserWorkerManager


def _make_manager():
    """BrowserWorkerManager 인스턴스 생성 (초기화 부작용 없이)."""
    mgr = object.__new__(BrowserWorkerManager)
    return mgr


class TestCheckWmiHealth:
    def test_check_wmi_health_success(self):
        """WMI 정상 시 (returncode=0) True 반환."""
        mgr = _make_manager()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = mgr._check_wmi_health()

        assert result is True
        mock_run.assert_called_once_with(
            ["python", "-c", "import platform; platform.machine()"],
            timeout=5,
            capture_output=True,
        )

    def test_check_wmi_health_timeout(self):
        """subprocess.TimeoutExpired 발생 시 False 반환."""
        mgr = _make_manager()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=5)):
            result = mgr._check_wmi_health()

        assert result is False


class TestFixWmi:
    def test_fix_wmi_calls_powershell(self):
        """_fix_wmi()가 Restart-Service winmgmt -Force 명령을 호출하는지 확인."""
        mgr = _make_manager()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = mgr._fix_wmi()

        assert result is True
        mock_run.assert_called_once_with(
            ["powershell", "-Command", "Restart-Service winmgmt -Force"],
            timeout=15,
            capture_output=True,
        )
