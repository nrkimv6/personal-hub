"""
PytestRunnerService — pytest subprocess 실행, JUnit XML 파싱, LLM 수정계획 요청 생성.
"""

import json
import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.test_run import TestRun, TestResult

logger = logging.getLogger("pytest_runner")

# 기본값
DEFAULT_TIMEOUT = 1800  # 30분
DEFAULT_TEST_PATH = "tests/"
LOG_DIR = Path(__file__).parent.parent.parent / "logs" / "pytest"
PROJECT_ROOT = Path(__file__).parent.parent.parent


class PytestRunnerService:
    """pytest 실행 서비스."""

    def __init__(self, db: Session):
        self.db = db

    # ========== 실행 ==========

    def run_tests(
        self,
        test_path: str = DEFAULT_TEST_PATH,
        extra_args: Optional[List[str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        triggered_by: str = TestRun.TRIGGERED_BY_MANUAL,
        schedule_run_id: Optional[int] = None,
    ) -> TestRun:
        """pytest를 subprocess로 실행하고 TestRun 레코드를 반환한다.

        Args:
            test_path: 실행 대상 경로 (기본: tests/)
            extra_args: 추가 pytest 인자 리스트
            timeout: 전체 실행 timeout(초)
            triggered_by: 트리거 출처 (scheduler/manual/api)
            schedule_run_id: 연결할 스케줄 실행 ID (nullable)

        Returns:
            완료(또는 실패) 상태의 TestRun
        """
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_path = LOG_DIR / f"{timestamp}.log"
        xml_path = LOG_DIR / f"{timestamp}.xml"

        extra_args = extra_args or []

        # TestRun 생성 (running)
        test_run = TestRun(
            status=TestRun.STATUS_RUNNING,
            triggered_by=triggered_by,
            test_path=test_path,
            extra_args=json.dumps(extra_args, ensure_ascii=False),
            log_file_path=str(log_path),
            xml_file_path=str(xml_path),
            schedule_run_id=schedule_run_id,
        )
        self.db.add(test_run)
        self.db.commit()
        self.db.refresh(test_run)

        cmd = [
            sys.executable, "-m", "pytest",
            test_path,
            "--tb=short",
            "--durations=0",
            "-q",
            f"--junitxml={xml_path}",
        ] + extra_args

        logger.info(f"pytest 실행 시작 (run_id={test_run.id}): {' '.join(cmd)}")

        try:
            with open(log_path, "w", encoding="utf-8") as log_fp:
                proc = subprocess.run(
                    cmd,
                    stdout=log_fp,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    cwd=str(PROJECT_ROOT),
                )

            logger.info(f"pytest 완료 (run_id={test_run.id}), exit_code={proc.returncode}")

            # XML 파싱
            if xml_path.exists():
                parsed = self.parse_junit_xml(str(xml_path))
                counts = self._count_statuses(parsed)
                self.save_results(test_run.id, parsed)
            else:
                parsed = []
                counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}

            test_run.mark_completed(
                total=counts["total"],
                passed=counts["passed"],
                failed=counts["failed"],
                errors=counts["errors"],
                skipped=counts["skipped"],
            )
            self.db.commit()

        except subprocess.TimeoutExpired:
            logger.error(f"pytest timeout (run_id={test_run.id}, timeout={timeout}s)")
            test_run.mark_failed(f"Timeout after {timeout}s")
            self.db.commit()

        except Exception as exc:
            logger.error(f"pytest 실행 오류 (run_id={test_run.id}): {exc}")
            test_run.mark_failed(str(exc))
            self.db.commit()

        self.db.refresh(test_run)
        return test_run

    # ========== 파싱 ==========

    @staticmethod
    def parse_junit_xml(xml_path: str) -> List[dict]:
        """JUnit XML을 파싱하여 테스트 결과 리스트를 반환한다 (duration 오름차순).

        Args:
            xml_path: JUnit XML 파일 경로

        Returns:
            테스트 결과 dict 리스트. 각 dict:
            {
                "test_name": str,
                "status": "passed"|"failed"|"error"|"skipped",
                "duration_seconds": float,
                "error_message": str|None,
                "traceback": str|None,
            }
        """
        path = Path(xml_path)
        if not path.exists():
            raise FileNotFoundError(f"JUnit XML not found: {xml_path}")

        content = path.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError(f"JUnit XML is empty: {xml_path}")

        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"JUnit XML parse error: {exc}") from exc

        results = []

        # testsuite 또는 testsuites 처리
        if root.tag == "testsuites":
            testcases = []
            for suite in root.findall("testsuite"):
                testcases.extend(suite.findall("testcase"))
        elif root.tag == "testsuite":
            testcases = root.findall("testcase")
        else:
            testcases = root.findall(".//testcase")

        for tc in testcases:
            classname = tc.get("classname", "")
            name = tc.get("name", "")
            time_str = tc.get("time", "0")

            try:
                duration = float(time_str)
            except (ValueError, TypeError):
                duration = 0.0

            # test_name 조합 (classname + name)
            if classname:
                test_name = f"{classname}::{name}"
            else:
                test_name = name

            # 상태 판단
            failure = tc.find("failure")
            error = tc.find("error")
            skipped = tc.find("skipped")

            if failure is not None:
                status = TestResult.STATUS_FAILED
                error_message = failure.get("message", "")
                traceback_text = failure.text or ""
            elif error is not None:
                status = TestResult.STATUS_ERROR
                error_message = error.get("message", "")
                traceback_text = error.text or ""
            elif skipped is not None:
                status = TestResult.STATUS_SKIPPED
                error_message = skipped.get("message", "")
                traceback_text = ""
            else:
                status = TestResult.STATUS_PASSED
                error_message = None
                traceback_text = None

            results.append({
                "test_name": test_name,
                "status": status,
                "duration_seconds": duration,
                "error_message": error_message or None,
                "traceback": traceback_text or None,
            })

        # duration 오름차순 정렬
        results.sort(key=lambda r: r["duration_seconds"])
        return results

    # ========== 저장 ==========

    def save_results(self, test_run_id: int, parsed_results: List[dict]) -> int:
        """파싱 결과를 TestResult 레코드로 일괄 저장한다.

        Returns:
            저장된 레코드 수
        """
        records = [
            TestResult(
                test_run_id=test_run_id,
                test_name=r["test_name"],
                status=r["status"],
                duration_seconds=r["duration_seconds"],
                error_message=r.get("error_message"),
                traceback=r.get("traceback"),
            )
            for r in parsed_results
        ]
        self.db.bulk_save_objects(records)
        self.db.commit()
        return len(records)

    # ========== LLM 요청 생성 ==========

    def create_fix_plan_requests(
        self,
        test_run_id: int,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        queue_name: str = "utility",
    ) -> List[int]:
        """실패 테스트에 대해 LLM 수정계획서 요청을 생성한다.

        Args:
            test_run_id: TestRun ID
            provider: LLM provider (None이면 resolver에 위임)
            model: 모델명 (None이면 resolver에 위임)
            queue_name: LLM 큐 이름

        Returns:
            생성된 LLMRequest ID 리스트
        """
        from app.modules.claude_worker.services.llm_service import LLMService

        failed_results = (
            self.db.query(TestResult)
            .filter(
                TestResult.test_run_id == test_run_id,
                TestResult.status.in_([TestResult.STATUS_FAILED, TestResult.STATUS_ERROR]),
            )
            .all()
        )

        if not failed_results:
            logger.info(f"실패 건 없음 (run_id={test_run_id})")
            return []

        llm_service = LLMService(self.db)
        request_ids = []

        for result in failed_results:
            safe_name = result.test_name.replace("/", "_").replace("::", "__")[:80]
            caller_id = f"{test_run_id}__{safe_name}"
            prompt = self._build_fix_prompt(result)

            req = llm_service.enqueue(
                caller_type="pytest_fix",
                caller_id=caller_id,
                prompt=prompt,
                requested_by="scheduler",
                request_source="pytest_auto_run",
                provider=provider,
                model=model,
                queue_name=queue_name,
            )

            # enqueue()가 mock으로 대체된 경우에도 FK 연결이 가능하도록 세션에 붙인다.
            self.db.add(req)
            self.db.flush()
            # TestResult에 llm_request_id 연결
            result.llm_request_id = req.id
            request_ids.append(req.id)

        self.db.commit()
        logger.info(f"LLM 수정계획 요청 {len(request_ids)}건 생성 (run_id={test_run_id})")
        return request_ids

    @staticmethod
    def _build_fix_prompt(test_result: TestResult) -> str:
        """실패 테스트에 대한 LLM 프롬프트 생성."""
        MAX_TRACEBACK = 3000

        error_section = ""
        if test_result.error_message:
            error_section += f"\n**에러 메시지:**\n```\n{test_result.error_message}\n```\n"

        tb = test_result.traceback or ""
        if len(tb) > MAX_TRACEBACK:
            tb = tb[:MAX_TRACEBACK] + "\n... (truncated)"
        if tb:
            error_section += f"\n**Traceback:**\n```\n{tb}\n```\n"

        return f"""# pytest 테스트 실패 수정 계획서 작성

아래 테스트가 실패했습니다. 프로젝트 루트에서 관련 소스를 Read 도구로 읽고, 실패 원인을 분석하여 수정 계획서를 마크다운으로 작성해 주세요.

## 실패 테스트 정보

- **테스트 이름:** `{test_result.test_name}`
- **상태:** `{test_result.status}`
{error_section}

## 요청 사항

1. 관련 소스 파일을 Read 도구로 읽으세요 (테스트 파일 + 대상 소스 파일).
2. 실패 원인을 분석하세요.
3. 아래 형식으로 수정 계획서를 작성하세요:

---

# 수정 계획: {test_result.test_name}

## 실패 원인
(원인 분석)

## 수정 방안
(구체적인 수정 방법)

## 영향 범위
(수정 시 영향받는 다른 코드/기능)

## 수정 우선순위
(즉시 / 다음 스프린트 / 나중에)
"""

    # ========== 내부 헬퍼 ==========

    @staticmethod
    def _count_statuses(parsed_results: List[dict]) -> dict:
        """파싱 결과에서 상태별 카운트 산출."""
        total = len(parsed_results)
        passed = sum(1 for r in parsed_results if r["status"] == TestResult.STATUS_PASSED)
        failed = sum(1 for r in parsed_results if r["status"] == TestResult.STATUS_FAILED)
        errors = sum(1 for r in parsed_results if r["status"] == TestResult.STATUS_ERROR)
        skipped = sum(1 for r in parsed_results if r["status"] == TestResult.STATUS_SKIPPED)
        return {"total": total, "passed": passed, "failed": failed, "errors": errors, "skipped": skipped}


# ========== 독립 유틸: playwright 미의존 ==========

def should_run_cron_now(schedule_value: str, last_run_at: Optional[datetime]) -> bool:
    """cron/time_window 스케줄이 지금 실행될 시간인지 판단.

    schedule_value에서 HH:MM 형태를 읽어 ±5분 tolerance로 비교.
    오늘 이미 실행됐으면 False (1일 1회 보장).

    Args:
        schedule_value: 스케줄 값 (cron 표현식 또는 JSON {"time": "HH:MM"})
        last_run_at: 마지막 실행 시각 (None이면 최초 실행 허용)

    Returns:
        True이면 지금 실행
    """
    now = datetime.now()

    if last_run_at and last_run_at.date() == now.date():
        return False

    try:
        sv = (schedule_value or "").strip()
        run_time_str = None

        if sv.startswith("{"):
            sv_dict = json.loads(sv)
            run_time_str = sv_dict.get("time") or sv_dict.get("run_time")
            if not run_time_str:
                windows = sv_dict.get("time_windows", [])
                if windows:
                    first = windows[0]
                    run_time_str = first.get("start") if isinstance(first, dict) else None
        else:
            parts = sv.split()
            if len(parts) >= 2:
                run_time_str = f"{parts[1]}:{parts[0].zfill(2)}"
            else:
                run_time_str = sv

        if not run_time_str:
            return False

        run_h, run_m = map(int, run_time_str.split(":"))
        target_minutes = run_h * 60 + run_m
        now_minutes = now.hour * 60 + now.minute
        return abs(now_minutes - target_minutes) <= 5

    except Exception:
        return False
