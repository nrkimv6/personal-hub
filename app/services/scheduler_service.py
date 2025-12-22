"""
Windows 작업 스케줄러 관리 서비스
"""
import subprocess
import csv
import sys
import logging
from io import StringIO
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SchedulerService:
    """Windows 작업 스케줄러 관리 서비스"""

    TASK_FOLDER = "MonitorPage"

    # 허용된 작업명 목록 (보안: 명령어 인젝션 방지)
    ALLOWED_TASKS = frozenset([
        "InstagramWatchdog",
        "DailyMaintenance",
        "WeeklyVacuum",
    ])

    def _validate_task_name(self, name: str) -> None:
        """작업명 검증 (허용 목록에 없으면 예외)"""
        if name not in self.ALLOWED_TASKS:
            raise ValueError(f"허용되지 않은 작업명: {name}")

    def _check_platform(self) -> None:
        """Windows 플랫폼 검사"""
        if sys.platform != "win32":
            raise RuntimeError("Windows 작업 스케줄러는 Windows에서만 사용 가능합니다")

    def _get_encoding(self) -> str:
        """시스템에 맞는 인코딩 반환"""
        # 한글 Windows에서는 cp949 사용
        return "cp949"

    def get_tasks(self) -> List[dict]:
        """등록된 작업 목록 조회"""
        self._check_platform()

        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/query",
                    "/fo",
                    "CSV",
                    "/v",
                    "/tn",
                    f"\\{self.TASK_FOLDER}\\*",
                ],
                capture_output=True,
                text=True,
                encoding=self._get_encoding(),
            )

            if result.returncode != 0:
                logger.warning(f"schtasks query failed: {result.stderr}")
                return []

            return self._parse_csv(result.stdout)
        except FileNotFoundError:
            logger.error("schtasks command not found")
            return []
        except Exception as e:
            logger.error(f"Failed to get tasks: {e}")
            return []

    def get_task(self, name: str) -> Optional[dict]:
        """특정 작업 상세 조회"""
        self._check_platform()
        self._validate_task_name(name)

        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/query",
                    "/fo",
                    "CSV",
                    "/v",
                    "/tn",
                    f"\\{self.TASK_FOLDER}\\{name}",
                ],
                capture_output=True,
                text=True,
                encoding=self._get_encoding(),
            )

            if result.returncode != 0:
                return None

            tasks = self._parse_csv(result.stdout)
            return tasks[0] if tasks else None
        except Exception as e:
            logger.error(f"Failed to get task {name}: {e}")
            return None

    def run_task(self, name: str) -> bool:
        """작업 즉시 실행"""
        self._check_platform()
        self._validate_task_name(name)

        try:
            result = subprocess.run(
                ["schtasks", "/run", "/tn", f"\\{self.TASK_FOLDER}\\{name}"],
                capture_output=True,
                text=True,
                encoding=self._get_encoding(),
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to run task {name}: {e}")
            return False

    def enable_task(self, name: str) -> bool:
        """작업 활성화"""
        self._check_platform()
        self._validate_task_name(name)

        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/change",
                    "/tn",
                    f"\\{self.TASK_FOLDER}\\{name}",
                    "/enable",
                ],
                capture_output=True,
                text=True,
                encoding=self._get_encoding(),
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to enable task {name}: {e}")
            return False

    def disable_task(self, name: str) -> bool:
        """작업 비활성화"""
        self._check_platform()
        self._validate_task_name(name)

        try:
            result = subprocess.run(
                [
                    "schtasks",
                    "/change",
                    "/tn",
                    f"\\{self.TASK_FOLDER}\\{name}",
                    "/disable",
                ],
                capture_output=True,
                text=True,
                encoding=self._get_encoding(),
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to disable task {name}: {e}")
            return False

    def _parse_csv(self, csv_text: str) -> List[dict]:
        """schtasks CSV 출력 파싱"""
        try:
            reader = csv.DictReader(StringIO(csv_text))
            tasks = []

            for row in reader:
                # TaskName에서 폴더 경로 제거하고 이름만 추출
                task_name = row.get("TaskName", "")
                if "\\" in task_name:
                    task_name = task_name.split("\\")[-1]

                # 허용된 작업만 포함
                if task_name not in self.ALLOWED_TASKS:
                    continue

                tasks.append(
                    {
                        "name": task_name,
                        "folder": self.TASK_FOLDER,
                        "status": row.get("Status", ""),
                        "last_run_time": self._parse_datetime(
                            row.get("Last Run Time")
                        ),
                        "last_result": self._parse_result(row.get("Last Result")),
                        "next_run_time": self._parse_datetime(
                            row.get("Next Run Time")
                        ),
                        "schedule": row.get("Schedule Type", ""),
                        "enabled": row.get("Scheduled Task State") == "Enabled",
                    }
                )

            return tasks
        except Exception as e:
            logger.error(f"Failed to parse CSV: {e}")
            return []

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """날짜/시간 문자열 파싱"""
        if not value or value in ("N/A", "해당 없음"):
            return None
        try:
            # 한글 Windows 형식: 2025-12-21 오후 2:30:00
            # 영문 Windows 형식: 12/21/2025 2:30:00 PM
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %p %I:%M:%S",
                "%m/%d/%Y %I:%M:%S %p",
            ]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            return None
        except Exception:
            return None

    def _parse_result(self, value: Optional[str]) -> Optional[int]:
        """실행 결과 코드 파싱"""
        if not value or value in ("N/A", "해당 없음"):
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


# 싱글톤 인스턴스
scheduler_service = SchedulerService()
