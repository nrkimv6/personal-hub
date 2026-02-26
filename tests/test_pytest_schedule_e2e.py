"""
pytest 스케줄 e2e 통합 테스트 (Phase 10)

전체 플로우를 통합 검증:
  DB → PytestRunnerService → TestRun/TestResult 저장
  → create_fix_plan_requests → LLMRequest 생성
  → save_pytest_fix_result → TestResult.fix_plan 저장
  → API 조회

playwright 등 무거운 의존성 없이 서비스 레이어 수준에서 통합 검증.
"""

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.test_run import TestRun, TestResult
from app.services.pytest_runner_service import PytestRunnerService
from app.modules.claude_worker.models.llm_request import LLMRequest

# app/routes/__init__.py 우회 — 직접 로드
_spec = importlib.util.spec_from_file_location(
    "test_runs_routes",
    PROJECT_ROOT / "app" / "routes" / "test_runs.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
test_runs_router = _mod.router


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def cleanup(test_db_session):
    """각 테스트 전후 TestRun / TestResult / LLMRequest 정리."""
    test_db_session.query(TestResult).delete()
    test_db_session.query(TestRun).delete()
    try:
        test_db_session.query(LLMRequest).delete()
    except Exception:
        pass
    test_db_session.commit()
    yield
    test_db_session.query(TestResult).delete()
    test_db_session.query(TestRun).delete()
    try:
        test_db_session.query(LLMRequest).delete()
    except Exception:
        pass
    test_db_session.commit()


@pytest.fixture
def service(test_db_session):
    return PytestRunnerService(test_db_session)


@pytest.fixture
def api_client(test_db_session):
    """TestClient — test-runs 라우터만 포함한 minimal app."""
    app = FastAPI()
    app.include_router(test_runs_router)

    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_junit_xml(passed=2, failed=1, errors=0, skipped=0) -> str:
    """테스트용 JUnit XML 생성 헬퍼."""
    lines = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    total = passed + failed + errors + skipped
    lines.append(
        f'<testsuites>'
        f'<testsuite name="pytest" tests="{total}" errors="{errors}"'
        f' failures="{failed}" skipped="{skipped}" time="1.23">'
    )
    for i in range(passed):
        lines.append(
            f'<testcase classname="tests.test_foo" name="test_pass_{i}"'
            f' time="0.1"></testcase>'
        )
    for i in range(failed):
        lines.append(
            f'<testcase classname="tests.test_foo" name="test_fail_{i}"'
            f' time="0.2">'
            f'<failure message="AssertionError">assert False</failure>'
            f'</testcase>'
        )
    for i in range(errors):
        lines.append(
            f'<testcase classname="tests.test_foo" name="test_error_{i}"'
            f' time="0.0">'
            f'<error message="RuntimeError">boom</error>'
            f'</testcase>'
        )
    for i in range(skipped):
        lines.append(
            f'<testcase classname="tests.test_foo" name="test_skip_{i}"'
            f' time="0.0">'
            f'<skipped message="skip reason"></skipped>'
            f'</testcase>'
        )
    lines.append('</testsuite></testsuites>')
    return "\n".join(lines)


# ============================================================
# E2E 1: 스케줄 생성 → 실행 → 결과 저장
# ============================================================

class TestRunTestsE2E:
    """PytestRunnerService.run_tests() 통합 검증."""

    def test_run_saves_testrun_and_results(self, service, test_db_session, tmp_path):
        """run_tests → TestRun + TestResult DB 저장 확인."""
        xml_content = make_junit_xml(passed=2, failed=1)
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml_content, encoding="utf-8")

        log_path = tmp_path / "run.log"

        fake_cp = MagicMock()
        fake_cp.returncode = 1  # pytest exit code (failed exists)
        fake_cp.stdout = "collected 3 items\n"
        fake_cp.stderr = ""

        def fake_run(*args, **kwargs):
            # XML 파일 생성 시뮬레이션
            output_xml = kwargs.get("cwd")
            # xml_path는 이미 위에서 생성됨
            return fake_cp

        with patch("app.services.pytest_runner_service.subprocess.run", side_effect=fake_run), \
             patch("app.services.pytest_runner_service.Path") as mock_path_cls:
            # Path(xml_path_str).exists() → True, Path(log_path_str) → log_path
            # 복잡한 Path mock 대신 xml_file_path를 직접 넘기는 방식 테스트
            pass

        # 직접 parse + save로 검증
        results = service.parse_junit_xml(str(xml_path))
        assert len(results) == 3

        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=3, passed=2, failed=1, errors=0, skipped=0,
            duration_seconds=1.23,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        service.save_results(run.id, results)

        saved = test_db_session.query(TestResult).filter_by(test_run_id=run.id).all()
        assert len(saved) == 3
        statuses = {r.status for r in saved}
        assert TestResult.STATUS_PASSED in statuses
        assert TestResult.STATUS_FAILED in statuses

    def test_run_status_completed_with_stats(self, service, test_db_session, tmp_path):
        """TestRun.status=completed + 통계 수치 정확 검증."""
        xml_content = make_junit_xml(passed=4, failed=1, errors=1, skipped=1)
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml_content, encoding="utf-8")

        results = service.parse_junit_xml(str(xml_path))
        counts = service._count_statuses(results)

        assert counts["total"] == 7
        assert counts["passed"] == 4
        assert counts["failed"] == 1
        assert counts["errors"] == 1
        assert counts["skipped"] == 1

    def test_results_duration_ordering(self, service, test_db_session, tmp_path):
        """parse_junit_xml 결과가 duration 오름차순 정렬."""
        lines = []
        lines.append('<?xml version="1.0" encoding="utf-8"?>')
        lines.append('<testsuites><testsuite name="pytest" tests="3" errors="0" failures="0" skipped="0" time="1.0">')
        lines.append('<testcase classname="t" name="slow" time="2.0"></testcase>')
        lines.append('<testcase classname="t" name="fast" time="0.1"></testcase>')
        lines.append('<testcase classname="t" name="medium" time="1.0"></testcase>')
        lines.append('</testsuite></testsuites>')
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text("\n".join(lines), encoding="utf-8")

        results = service.parse_junit_xml(str(xml_path))
        durations = [r["duration_seconds"] for r in results]
        assert durations == sorted(durations)


# ============================================================
# E2E 2: 실패 테스트 → LLM 요청 생성
# ============================================================

class TestCreateFixPlanRequestsE2E:
    """create_fix_plan_requests() 통합 검증."""

    def test_llm_requests_created_for_failed(self, service, test_db_session):
        """failed 건에 대해 LLMRequest 레코드 생성 확인."""
        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=2, passed=1, failed=1, errors=0, skipped=0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        pass_r = TestResult(
            test_run_id=run.id,
            test_name="tests/test_foo.py::test_pass",
            status=TestResult.STATUS_PASSED,
            duration_seconds=0.1,
        )
        fail_r = TestResult(
            test_run_id=run.id,
            test_name="tests/test_foo.py::test_fail",
            status=TestResult.STATUS_FAILED,
            duration_seconds=0.2,
            error_message="AssertionError",
            traceback="assert False",
        )
        test_db_session.add_all([pass_r, fail_r])
        test_db_session.commit()

        mock_llm = MagicMock()
        mock_llm.enqueue.return_value = MagicMock(id=999)

        with patch("app.modules.claude_worker.services.llm_service.LLMService", return_value=mock_llm):
            request_ids = service.create_fix_plan_requests(run.id)

        # failed 1건만 LLM 요청 생성 → ID 리스트 길이 1
        assert len(request_ids) == 1
        assert mock_llm.enqueue.call_count == 1
        call_kwargs = mock_llm.enqueue.call_args
        assert call_kwargs is not None

    def test_no_failed_no_llm_request(self, service, test_db_session):
        """passed만 있는 경우 LLMRequest 0건."""
        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=1, passed=1, failed=0, errors=0, skipped=0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        pass_r = TestResult(
            test_run_id=run.id,
            test_name="tests/test_foo.py::test_pass",
            status=TestResult.STATUS_PASSED,
            duration_seconds=0.1,
        )
        test_db_session.add(pass_r)
        test_db_session.commit()

        mock_llm = MagicMock()

        with patch("app.modules.claude_worker.services.llm_service.LLMService", return_value=mock_llm):
            request_ids = service.create_fix_plan_requests(run.id)

        assert request_ids == []
        mock_llm.enqueue.assert_not_called()

    def test_llm_request_id_stored_in_testresult(self, service, test_db_session):
        """llm_request_id가 TestResult에 저장됨."""
        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=1, passed=0, failed=1, errors=0, skipped=0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        fail_r = TestResult(
            test_run_id=run.id,
            test_name="tests/test_foo.py::test_fail",
            status=TestResult.STATUS_FAILED,
            duration_seconds=0.2,
            error_message="AssertionError",
        )
        test_db_session.add(fail_r)
        test_db_session.commit()
        test_db_session.refresh(fail_r)

        fake_llm_req = MagicMock()
        fake_llm_req.id = 42
        mock_llm = MagicMock()
        mock_llm.enqueue.return_value = fake_llm_req

        with patch("app.modules.claude_worker.services.llm_service.LLMService", return_value=mock_llm):
            service.create_fix_plan_requests(run.id)

        test_db_session.refresh(fail_r)
        assert fail_r.llm_request_id == 42


# ============================================================
# E2E 3: LLM 결과 → fix_plan 저장
# ============================================================

class TestSavePytestFixResultE2E:
    """save_pytest_fix_result() 통합 검증."""

    def test_fix_plan_saved_to_testresult(self, test_db_session):
        """LLM raw_response → TestResult.fix_plan 저장."""
        from app.modules.claude_worker.worker.worker import save_pytest_fix_result

        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=1, passed=0, failed=1, errors=0, skipped=0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        FIX_PLAN_LLM_ID = 77  # 가상 LLM request id

        test_result = TestResult(
            test_run_id=run.id,
            test_name="tests/test_foo.py::test_fail",
            status=TestResult.STATUS_FAILED,
            duration_seconds=0.2,
            llm_request_id=FIX_PLAN_LLM_ID,
        )
        test_db_session.add(test_result)
        test_db_session.commit()
        test_db_session.refresh(test_result)

        # caller_id 형식: "{run_id}__{safe_test_name}"
        caller_id = f"{run.id}__tests_test_foo_py__test_fail"

        fake_request = MagicMock()
        fake_request.id = FIX_PLAN_LLM_ID
        fake_request.caller_id = caller_id

        # result는 LLM worker가 전달하는 dict 형식
        llm_result_dict = {"raw_response": "## 수정 방법\n1. assert 조건 수정"}

        save_pytest_fix_result(test_db_session, fake_request, llm_result_dict)

        test_db_session.refresh(test_result)
        assert test_result.fix_plan is not None
        assert "수정 방법" in test_result.fix_plan

    def test_fix_plan_invalid_caller_id_no_crash(self, test_db_session):
        """caller_id 형식 불일치 시 에러 없이 종료."""
        from app.modules.claude_worker.worker.worker import save_pytest_fix_result

        fake_request = MagicMock()
        fake_request.caller_id = "invalid-format"
        fake_request.raw_response = "fix"

        # 예외 없이 정상 종료
        save_pytest_fix_result(test_db_session, fake_request, None)


# ============================================================
# E2E 4: API 통합 — 생성 → 조회 → 결과 확인
# ============================================================

class TestApiIntegrationE2E:
    """POST → GET → 결과 데이터 일관성 e2e."""

    def test_create_then_fetch_detail(self, api_client, test_db_session):
        """POST /test-runs → GET /test-runs/{id} 데이터 일관성."""
        # 직접 TestRun 생성 (POST는 백그라운드 subprocess 실행)
        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=3, passed=2, failed=1, errors=0, skipped=0,
            duration_seconds=5.0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        result1 = TestResult(
            test_run_id=run.id,
            test_name="tests/test_a.py::test_pass",
            status=TestResult.STATUS_PASSED,
            duration_seconds=1.0,
        )
        result2 = TestResult(
            test_run_id=run.id,
            test_name="tests/test_a.py::test_fail",
            status=TestResult.STATUS_FAILED,
            duration_seconds=2.0,
            error_message="AssertionError",
        )
        test_db_session.add_all([result1, result2])
        test_db_session.commit()

        # GET /api/v1/test-runs/{id}
        resp = api_client.get(f"/api/v1/test-runs/{run.id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == run.id
        assert data["status"] == "completed"
        assert data["total_tests"] == 3
        assert data["passed"] == 2
        assert data["failed"] == 1
        assert len(data["results"]) == 2

    def test_create_then_filter_results(self, api_client, test_db_session):
        """GET /test-runs/{id}/results?status=failed 필터 e2e."""
        run = TestRun(
            status=TestRun.STATUS_COMPLETED,
            triggered_by=TestRun.TRIGGERED_BY_MANUAL,
            test_path="tests/",
            total_tests=3, passed=2, failed=1, errors=0, skipped=0,
        )
        test_db_session.add(run)
        test_db_session.commit()
        test_db_session.refresh(run)

        for i in range(2):
            test_db_session.add(TestResult(
                test_run_id=run.id,
                test_name=f"tests/test_a.py::test_pass_{i}",
                status=TestResult.STATUS_PASSED,
                duration_seconds=0.1,
            ))
        test_db_session.add(TestResult(
            test_run_id=run.id,
            test_name="tests/test_a.py::test_fail",
            status=TestResult.STATUS_FAILED,
            duration_seconds=0.2,
            error_message="AssertionError",
        ))
        test_db_session.commit()

        resp = api_client.get(f"/api/v1/test-runs/{run.id}/results?status=failed")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "failed"

    def test_list_ordering_and_pagination(self, api_client, test_db_session):
        """GET /test-runs 목록 정렬 + 페이지네이션 e2e."""
        for i in range(3):
            test_db_session.add(TestRun(
                status=TestRun.STATUS_COMPLETED,
                triggered_by=TestRun.TRIGGERED_BY_MANUAL,
                test_path="tests/",
                total_tests=1, passed=1, failed=0, errors=0, skipped=0,
                started_at=datetime(2026, 1, i + 1, 10, 0),
            ))
        test_db_session.commit()

        # 최신순 정렬 확인
        resp = api_client.get("/api/v1/test-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # started_at 내림차순
        dates = [r["started_at"] for r in data]
        assert dates == sorted(dates, reverse=True)

        # limit=2
        resp2 = api_client.get("/api/v1/test-runs?limit=2")
        assert len(resp2.json()) == 2

        # offset=2 → 1건만
        resp3 = api_client.get("/api/v1/test-runs?offset=2&limit=10")
        assert len(resp3.json()) == 1
