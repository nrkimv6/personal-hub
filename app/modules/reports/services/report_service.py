"""Report generation service."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict
from sqlalchemy.orm import Session

from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.models.llm_request import LLMRequest

logger = logging.getLogger(__name__)


class ReportService:
    """보고서 생성 서비스."""

    SLEEP_NOW_LOG_DIR = r"D:\work\project\tools\sleep-now\logs"
    NIGHTLY_CLEANUP_LOG_DIR = r"D:\work\project\service\wtools\common\scripts\logs"

    def __init__(self, db: Session):
        self.db = db
        self.llm_service = LLMService(db)

    def collect_nightly_cleanup_logs(self, date: datetime) -> Dict[str, str]:
        """nightly-done-cleanup 로그 수집.

        Args:
            date: 분석할 날짜 (새벽 2시 실행 기준)

        Returns:
            dict: {
                "cleanup_log": str,
                "date": str
            }
        """
        log_dir = Path(self.NIGHTLY_CLEANUP_LOG_DIR)
        date_str = date.strftime("%Y-%m-%d")

        # done-cleanup-YYYY-MM-DD.log
        cleanup_log = ""
        log_file = log_dir / f"done-cleanup-{date_str}.log"
        if log_file.exists():
            try:
                cleanup_log = log_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to read cleanup log: {e}")
                cleanup_log = f"(로그 읽기 실패: {e})"

        return {
            "cleanup_log": cleanup_log or "(로그 없음 - 실행되지 않았거나 파일을 찾을 수 없음)",
            "date": date_str
        }

    def collect_sleep_now_logs(self, date: datetime) -> Dict[str, str]:
        """sleep-now 로그 수집.

        Args:
            date: 분석할 날짜 (해당 날짜 야간 실행 = 전날 23:50 ~ 당일 07:00)

        Returns:
            dict: {
                "service_log": str,
                "scheduler_log": str,
                "error_log": str,
                "date": str
            }
        """
        log_dir = Path(self.SLEEP_NOW_LOG_DIR)
        date_str = date.strftime("%Y%m%d")
        prev_date_str = (date - timedelta(days=1)).strftime("%Y%m%d")

        # service_runner.log - 최근 100줄 (해당 날짜 필터링)
        service_log = ""
        service_log_path = log_dir / "service_runner.log"
        if service_log_path.exists():
            try:
                lines = service_log_path.read_text(encoding="utf-8").splitlines()
                # 전날 23시 ~ 당일 07시 사이 로그만 필터링
                filtered = [l for l in lines[-200:] if prev_date_str in l or date_str in l]
                service_log = "\n".join(filtered[-100:])
            except Exception as e:
                logger.error(f"Failed to read service log: {e}")

        # scheduler_*.log - 해당 날짜 파일 찾기
        scheduler_log = ""
        try:
            for log_file in sorted(log_dir.glob(f"scheduler_{date_str}*.log"), reverse=True):
                scheduler_log = log_file.read_text(encoding="utf-8")[-10000:]  # 최대 10KB
                break
            # 전날 파일도 확인 (23:50에 시작했을 수 있음)
            if not scheduler_log:
                for log_file in sorted(log_dir.glob(f"scheduler_{prev_date_str}*.log"), reverse=True):
                    scheduler_log = log_file.read_text(encoding="utf-8")[-10000:]
                    break
        except Exception as e:
            logger.error(f"Failed to read scheduler log: {e}")

        # scheduler_err_*.log
        error_log = ""
        try:
            for log_file in sorted(log_dir.glob(f"scheduler_err_{date_str}*.log"), reverse=True):
                content = log_file.read_text(encoding="utf-8").strip()
                if content:
                    error_log = content[-5000:]  # 최대 5KB
                break
        except Exception as e:
            logger.error(f"Failed to read error log: {e}")

        return {
            "service_log": service_log or "(로그 없음)",
            "scheduler_log": scheduler_log or "(로그 없음)",
            "error_log": error_log or "(에러 없음)",
            "date": date.strftime("%Y-%m-%d")
        }

    def collect_daily_data(self, date: datetime) -> Dict:
        """일일 데이터 수집.

        Args:
            date: 분석할 날짜

        Returns:
            dict: 시스템 통계 데이터
        """
        # TODO: TaskScheduleRun, LLMRequest 통계 수집
        # TODO: InstagramPost 통계
        # TODO: GeneratedWriting 통계
        return {
            "date": date.strftime("%Y-%m-%d"),
            "tasks": {},
            "llm": {},
            "instagram": {},
            "writing": {}
        }

    def generate_report_prompt(
        self,
        report_type: str,
        data: Dict
    ) -> str:
        """보고서 프롬프트 생성.

        Args:
            report_type: 보고서 타입
            data: 프롬프트 데이터

        Returns:
            프롬프트 문자열
        """
        from app.modules.reports.prompts import nightly_cleanup, sleep_now, daily_summary

        if report_type == "nightly_cleanup":
            return nightly_cleanup.NIGHTLY_CLEANUP_REPORT_PROMPT.format(**data)
        elif report_type == "sleep_now":
            return sleep_now.SLEEP_NOW_REPORT_PROMPT.format(**data)
        elif report_type == "daily_summary":
            return daily_summary.DAILY_SUMMARY_PROMPT.format(
                data_json=json.dumps(data, ensure_ascii=False, indent=2),
                date=data.get("date", "")
            )
        else:
            raise ValueError(f"Unknown report type: {report_type}")

    def request_report(
        self,
        report_type: str,
        period_start: datetime,
        period_end: datetime,
        config: Dict = None
    ) -> LLMRequest:
        """LLM에 보고서 생성 요청.

        Args:
            report_type: 보고서 타입
            period_start: 기간 시작
            period_end: 기간 종료
            config: 추가 설정

        Returns:
            생성된 LLMRequest
        """
        if report_type == "nightly_cleanup":
            data = self.collect_nightly_cleanup_logs(period_end)  # 당일 기준
        elif report_type == "sleep_now":
            data = self.collect_sleep_now_logs(period_end)  # 당일 기준
        else:
            data = self.collect_daily_data(period_start)

        prompt = self.generate_report_prompt(report_type, data)

        return self.llm_service.enqueue(
            caller_type="report",
            caller_id=f"{report_type}_{period_end.strftime('%Y%m%d')}",
            prompt=prompt
        )
