"""
스케줄러 서비스 단위 테스트
"""
import pytest
import sys
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.services.scheduler_service import SchedulerService


class TestSchedulerServiceValidation:
    """작업명 검증 테스트"""

    def setup_method(self):
        self.service = SchedulerService()

    def test_validate_task_name_allowed(self):
        """허용된 작업명은 예외 없이 통과"""
        # 허용된 작업명들
        for name in ["DailyMaintenance", "WeeklyVacuum", "LogCleanup", "APIWatchdog"]:
            # 예외가 발생하지 않아야 함
            self.service._validate_task_name(name)

    def test_validate_task_name_R_apiwatchdog_allowed(self):
        """R: APIWatchdog는 whitelist에 포함되어야 한다."""
        self.service._validate_task_name("APIWatchdog")

    def test_validate_task_name_not_allowed(self):
        """허용되지 않은 작업명은 ValueError 발생"""
        with pytest.raises(ValueError) as exc_info:
            self.service._validate_task_name("MaliciousTask")
        assert "허용되지 않은 작업명" in str(exc_info.value)

    def test_validate_task_name_injection_attempt(self):
        """명령어 인젝션 시도 차단"""
        injection_attempts = [
            "Task; rm -rf /",
            "Task && malicious_command",
            "Task | cat /etc/passwd",
            "../../../etc/passwd",
            "Task`whoami`",
        ]
        for attempt in injection_attempts:
            with pytest.raises(ValueError):
                self.service._validate_task_name(attempt)


class TestSchedulerServicePlatform:
    """플랫폼 검사 테스트"""

    def setup_method(self):
        self.service = SchedulerService()

    def test_check_platform_windows(self):
        """Windows에서는 예외 없이 통과"""
        with patch.object(sys, "platform", "win32"):
            # 예외가 발생하지 않아야 함
            self.service._check_platform()

    def test_check_platform_non_windows(self):
        """비-Windows에서는 RuntimeError 발생"""
        with patch.object(sys, "platform", "linux"):
            with pytest.raises(RuntimeError) as exc_info:
                self.service._check_platform()
            assert "Windows" in str(exc_info.value)

        with patch.object(sys, "platform", "darwin"):
            with pytest.raises(RuntimeError):
                self.service._check_platform()


class TestSchedulerServiceParsing:
    """CSV 파싱 테스트"""

    def setup_method(self):
        self.service = SchedulerService()

    def test_parse_datetime_valid_formats(self):
        """유효한 날짜 형식 파싱"""
        # ISO 형식
        result = self.service._parse_datetime("2025-12-21 14:30:00")
        assert result == datetime(2025, 12, 21, 14, 30, 0)

    def test_parse_datetime_invalid(self):
        """유효하지 않은 날짜는 None 반환"""
        assert self.service._parse_datetime(None) is None
        assert self.service._parse_datetime("N/A") is None
        assert self.service._parse_datetime("해당 없음") is None
        assert self.service._parse_datetime("invalid") is None

    def test_parse_result_valid(self):
        """유효한 결과 코드 파싱"""
        assert self.service._parse_result("0") == 0
        assert self.service._parse_result("1") == 1
        assert self.service._parse_result("267009") == 267009

    def test_parse_result_invalid(self):
        """유효하지 않은 결과는 None 반환"""
        assert self.service._parse_result(None) is None
        assert self.service._parse_result("N/A") is None
        assert self.service._parse_result("해당 없음") is None
        assert self.service._parse_result("invalid") is None

    def test_parse_csv_filters_allowed_tasks(self):
        """CSV 파싱 시 허용된 작업만 포함"""
        csv_text = '''TaskName,Status,Scheduled Task State,Last Run Time,Last Result,Next Run Time,Schedule Type
\\MonitorPage\\APIWatchdog,Ready,Enabled,2025-12-21 14:00:00,0,2025-12-21 14:05:00,MINUTE
\\MonitorPage\\MaliciousTask,Ready,Enabled,N/A,N/A,N/A,DAILY
\\MonitorPage\\DailyMaintenance,Ready,Disabled,N/A,N/A,N/A,DAILY'''

        tasks = self.service._parse_csv(csv_text)

        # 허용된 작업만 포함되어야 함
        task_names = [t["name"] for t in tasks]
        assert "APIWatchdog" in task_names
        assert "DailyMaintenance" in task_names
        assert "MaliciousTask" not in task_names

    def test_parse_csv_empty(self):
        """빈 CSV는 빈 리스트 반환"""
        assert self.service._parse_csv("") == []

    def test_parse_csv_extracts_correct_fields(self):
        """CSV에서 올바른 필드 추출"""
        csv_text = '''TaskName,Status,Scheduled Task State,Last Run Time,Last Result,Next Run Time,Schedule Type
\\MonitorPage\\APIWatchdog,Running,Enabled,2025-12-21 14:00:00,0,2025-12-21 14:05:00,MINUTE'''

        tasks = self.service._parse_csv(csv_text)

        assert len(tasks) == 1
        task = tasks[0]
        assert task["name"] == "APIWatchdog"
        assert task["folder"] == "MonitorPage"
        assert task["status"] == "Running"
        assert task["enabled"] is True
        assert task["last_result"] == 0


class TestSchedulerServiceMocked:
    """subprocess 호출 모킹 테스트"""

    def setup_method(self):
        self.service = SchedulerService()

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_get_tasks_success(self, mock_run):
        """작업 목록 조회 성공"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='''TaskName,Status,Scheduled Task State,Last Run Time,Last Result,Next Run Time,Schedule Type
\\MonitorPage\\APIWatchdog,Ready,Enabled,N/A,N/A,N/A,MINUTE''',
        )

        tasks = self.service.get_tasks()

        assert len(tasks) == 1
        assert tasks[0]["name"] == "APIWatchdog"
        mock_run.assert_called_once()

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_get_tasks_empty_when_no_tasks(self, mock_run):
        """작업이 없으면 빈 리스트 반환"""
        mock_run.return_value = MagicMock(
            returncode=1,  # 실패
            stderr="No scheduled tasks",
        )

        tasks = self.service.get_tasks()
        assert tasks == []

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_run_task_success(self, mock_run):
        """작업 실행 성공"""
        mock_run.return_value = MagicMock(returncode=0)

        result = self.service.run_task("APIWatchdog")

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "schtasks" in call_args
        assert "/run" in call_args
        assert "\\MonitorPage\\APIWatchdog" in call_args

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_run_task_failure(self, mock_run):
        """작업 실행 실패"""
        mock_run.return_value = MagicMock(returncode=1)

        result = self.service.run_task("APIWatchdog")

        assert result is False

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_enable_task_success(self, mock_run):
        """작업 활성화 성공"""
        mock_run.return_value = MagicMock(returncode=0)

        result = self.service.enable_task("DailyMaintenance")

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "/enable" in call_args

    @patch("app.services.scheduler_service.subprocess.run")
    @patch.object(sys, "platform", "win32")
    def test_disable_task_success(self, mock_run):
        """작업 비활성화 성공"""
        mock_run.return_value = MagicMock(returncode=0)

        result = self.service.disable_task("WeeklyVacuum")

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "/disable" in call_args

    def test_get_task_validates_name(self):
        """get_task는 작업명을 검증"""
        with pytest.raises(ValueError):
            self.service.get_task("InvalidTask")

    def test_run_task_validates_name(self):
        """run_task는 작업명을 검증"""
        with pytest.raises(ValueError):
            self.service.run_task("InvalidTask")

    def test_enable_task_validates_name(self):
        """enable_task는 작업명을 검증"""
        with pytest.raises(ValueError):
            self.service.enable_task("InvalidTask")

    def test_disable_task_validates_name(self):
        """disable_task는 작업명을 검증"""
        with pytest.raises(ValueError):
            self.service.disable_task("InvalidTask")
