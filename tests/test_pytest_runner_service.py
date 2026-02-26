"""
PytestRunnerService 유닛 테스트

RIGHT-BICEP + CORRECT 원칙 적용:
- Right: 결과가 올바른가?
- Boundary: 경계값 (CORRECT: Conformance/Ordering/Range/Reference/Existence/Cardinality/Time)
- Inverse: 역관계 검증
- Cross-check: 교차 검증
- Error: 에러 조건 테스트

테스트 대상:
- PytestRunnerService.parse_junit_xml()
- PytestRunnerService.run_tests() (mock subprocess)
- PytestRunnerService.create_fix_plan_requests()
- PytestRunnerService._build_fix_prompt()
- PytestRunnerService.save_results()
- PytestRunnerService._count_statuses()
- should_run_cron_now() (독립 유틸 — playwright 미의존)
"""

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.pytest_runner_service import PytestRunnerService, should_run_cron_now
from app.models.test_run import TestRun, TestResult


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def runner(test_db_session):
    return PytestRunnerService(test_db_session)


def make_junit_xml(testcases: list) -> str:
    """JUnit XML 생성 헬퍼 (들여쓰기 없음 — XML 선언은 반드시 첫 번째 문자)."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    lines.append(f'<testsuite name="pytest" tests="{len(testcases)}">')
    for tc in testcases:
        name = tc.get("name", "test_foo")
        classname = tc.get("classname", "tests.test_foo")
        time_val = tc.get("time", "0.01")
        inner = ""
        if tc.get("failure"):
            msg = tc["failure"].get("message", "AssertionError")
            tb = tc["failure"].get("text", "traceback here")
            inner = f'<failure message="{msg}">{tb}</failure>'
        elif tc.get("error"):
            msg = tc["error"].get("message", "RuntimeError")
            tb = tc["error"].get("text", "error tb")
            inner = f'<error message="{msg}">{tb}</error>'
        elif tc.get("skipped"):
            inner = '<skipped message="skip reason"/>'
        lines.append(f'<testcase classname="{classname}" name="{name}" time="{time_val}">{inner}</testcase>')
    lines.append('</testsuite>')
    return '\n'.join(lines)


@pytest.fixture
def tmp_xml(tmp_path):
    """임시 XML 파일 경로 반환 팩토리."""
    def factory(content: str) -> str:
        p = tmp_path / "result.xml"
        p.write_text(content, encoding="utf-8")
        return str(p)
    return factory


@pytest.fixture
def sample_test_run(test_db_session):
    """TestRun fixture."""
    run = TestRun(
        status=TestRun.STATUS_RUNNING,
        triggered_by=TestRun.TRIGGERED_BY_MANUAL,
        test_path="tests/",
        total_tests=0, passed=0, failed=0, errors=0, skipped=0,
    )
    test_db_session.add(run)
    test_db_session.commit()
    test_db_session.refresh(run)
    return run


@pytest.fixture
def failed_test_result(test_db_session, sample_test_run):
    """실패 TestResult fixture."""
    result = TestResult(
        test_run_id=sample_test_run.id,
        test_name="tests/test_foo.py::TestFoo::test_bar",
        status=TestResult.STATUS_FAILED,
        duration_seconds=0.5,
        error_message="AssertionError: expected 1, got 2",
        traceback="AssertionError: expected 1, got 2\n  File test_foo.py, line 10",
    )
    test_db_session.add(result)
    test_db_session.commit()
    test_db_session.refresh(result)
    return result


# ============================================================
# 7-1. parse_junit_xml() 테스트
# ============================================================

class TestParseJunitXmlRight:
    """Right: 올바른 결과."""

    def test_passed_status(self, tmp_xml):
        """passed testcase → STATUS_PASSED."""
        xml = make_junit_xml([{"name": "test_ok", "classname": "tests.foo", "time": "0.1"}])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert len(results) == 1
        assert results[0]["status"] == TestResult.STATUS_PASSED

    def test_failed_status(self, tmp_xml):
        """failure 요소 → STATUS_FAILED."""
        xml = make_junit_xml([{
            "name": "test_fail", "classname": "tests.foo", "time": "0.2",
            "failure": {"message": "AssertionError", "text": "traceback"}
        }])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["status"] == TestResult.STATUS_FAILED
        assert results[0]["error_message"] == "AssertionError"
        assert "traceback" in results[0]["traceback"]

    def test_error_status(self, tmp_xml):
        """error 요소 → STATUS_ERROR."""
        xml = make_junit_xml([{
            "name": "test_err", "classname": "tests.foo", "time": "0.3",
            "error": {"message": "RuntimeError", "text": "err tb"}
        }])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["status"] == TestResult.STATUS_ERROR

    def test_skipped_status(self, tmp_xml):
        """skipped 요소 → STATUS_SKIPPED."""
        xml = make_junit_xml([{
            "name": "test_skip", "classname": "tests.foo", "time": "0.0",
            "skipped": True
        }])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["status"] == TestResult.STATUS_SKIPPED

    def test_duration_extracted(self, tmp_xml):
        """time 속성 → duration_seconds float."""
        xml = make_junit_xml([{"name": "test_t", "classname": "c", "time": "1.234"}])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert abs(results[0]["duration_seconds"] - 1.234) < 0.001

    def test_test_name_combined(self, tmp_xml):
        """classname::name 형식으로 test_name 조합."""
        xml = make_junit_xml([{"name": "test_method", "classname": "tests.module.TestClass", "time": "0.1"}])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["test_name"] == "tests.module.TestClass::test_method"


class TestParseJunitXmlBoundary:
    """Boundary: 경계값 (CORRECT)."""

    def test_ordering_duration_asc(self, tmp_xml):
        """Ordering: duration 오름차순 정렬."""
        xml = make_junit_xml([
            {"name": "slow", "classname": "c", "time": "2.0"},
            {"name": "fast", "classname": "c", "time": "0.1"},
            {"name": "mid", "classname": "c", "time": "1.0"},
        ])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        durations = [r["duration_seconds"] for r in results]
        assert durations == sorted(durations)

    def test_existence_empty_testsuite(self, tmp_xml):
        """Existence: 빈 testsuite → 빈 리스트."""
        xml = '<?xml version="1.0"?><testsuite tests="0"></testsuite>'
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results == []

    def test_existence_no_time_attr(self, tmp_xml):
        """Existence: time 속성 없음 → duration_seconds=0.0."""
        xml = '<testsuite tests="1"><testcase classname="c" name="t"/></testsuite>'
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["duration_seconds"] == 0.0

    def test_cardinality_single(self, tmp_xml):
        """Cardinality: 단일 testcase → 1개 결과."""
        xml = make_junit_xml([{"name": "only", "classname": "c", "time": "0.5"}])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert len(results) == 1

    def test_cardinality_many(self, tmp_xml):
        """Cardinality: 100건 testcase → 전체 파싱."""
        cases = [{"name": f"test_{i}", "classname": "c", "time": f"0.{i:03d}"} for i in range(100)]
        xml = make_junit_xml(cases)
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert len(results) == 100

    def test_range_zero_duration(self, tmp_xml):
        """Range: duration=0.0 처리."""
        xml = make_junit_xml([{"name": "t", "classname": "c", "time": "0.0"}])
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert results[0]["duration_seconds"] == 0.0

    def test_conformance_no_xml_declaration(self, tmp_xml):
        """Conformance: XML 선언 없는 파일도 파싱 가능."""
        xml = '<testsuite tests="1"><testcase classname="c" name="t" time="0.1"/></testsuite>'
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        assert len(results) == 1


class TestParseJunitXmlInverse:
    """Inverse: 역관계 검증."""

    def test_status_count_inverse(self, tmp_xml):
        """passed + failed + error + skipped == 전체 testcase 수."""
        cases = [
            {"name": "p1", "classname": "c", "time": "0.1"},
            {"name": "f1", "classname": "c", "time": "0.2", "failure": {"message": "err", "text": "tb"}},
            {"name": "s1", "classname": "c", "time": "0.0", "skipped": True},
        ]
        xml = make_junit_xml(cases)
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        counts = PytestRunnerService._count_statuses(results)
        assert counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"] == counts["total"]


class TestParseJunitXmlCrossCheck:
    """Cross-check: 교차 검증."""

    def test_cross_check_count_statuses(self, tmp_xml):
        """_count_statuses 결과가 parse 결과와 일치."""
        cases = [
            {"name": "p", "classname": "c", "time": "0.1"},
            {"name": "f", "classname": "c", "time": "0.2", "failure": {"message": "e", "text": "t"}},
        ]
        xml = make_junit_xml(cases)
        results = PytestRunnerService.parse_junit_xml(tmp_xml(xml))
        counts = PytestRunnerService._count_statuses(results)
        assert counts["passed"] == 1
        assert counts["failed"] == 1
        assert counts["total"] == 2


class TestParseJunitXmlError:
    """Error: 에러 조건."""

    def test_file_not_found(self):
        """존재하지 않는 경로 → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            PytestRunnerService.parse_junit_xml("/nonexistent/path/result.xml")

    def test_malformed_xml(self, tmp_xml):
        """잘못된 XML → ValueError."""
        with pytest.raises(ValueError, match="parse error"):
            PytestRunnerService.parse_junit_xml(tmp_xml("<broken><unclosed>"))

    def test_empty_file(self, tmp_xml):
        """빈 파일 → ValueError."""
        p = tmp_xml("")
        with pytest.raises(ValueError):
            PytestRunnerService.parse_junit_xml(p)


# ============================================================
# 7-2. run_tests() 테스트 (mock subprocess)
# ============================================================

class TestRunTestsRight:
    """Right: 올바른 결과 (mock subprocess)."""

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_creates_test_run_record(self, mock_subproc, runner, tmp_path):
        """정상 실행 → TestRun 생성, status=completed."""
        # XML 생성
        xml_content = make_junit_xml([
            {"name": "test_ok", "classname": "c", "time": "0.1"},
        ])

        def fake_run(cmd, stdout, stderr, timeout, cwd):
            # log 파일에 출력
            stdout.write("1 passed")
            # XML 파일 생성
            xml_path = next(a for a in cmd if "--junitxml" in a).split("=")[1]
            Path(xml_path).write_text(xml_content, encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_subproc.side_effect = fake_run

        test_run = runner.run_tests(test_path="tests/", triggered_by="manual")

        assert test_run.id is not None
        assert test_run.status == TestRun.STATUS_COMPLETED
        assert test_run.total_tests == 1
        assert test_run.passed == 1
        assert test_run.failed == 0

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_log_and_xml_files_created(self, mock_subproc, runner):
        """log/xml 파일 경로가 TestRun에 기록됨."""
        xml_content = make_junit_xml([])

        def fake_run(cmd, stdout, stderr, timeout, cwd):
            stdout.write("")
            xml_path = next(a for a in cmd if "--junitxml" in a).split("=")[1]
            Path(xml_path).write_text(xml_content, encoding="utf-8")
            m = MagicMock()
            m.returncode = 0
            return m

        mock_subproc.side_effect = fake_run
        run = runner.run_tests()
        assert run.log_file_path is not None
        assert run.xml_file_path is not None

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_failed_tests_counted(self, mock_subproc, runner):
        """failed 건이 TestRun.failed에 반영됨."""
        xml_content = make_junit_xml([
            {"name": "ok", "classname": "c", "time": "0.1"},
            {"name": "fail", "classname": "c", "time": "0.2",
             "failure": {"message": "err", "text": "tb"}},
        ])

        def fake_run(cmd, stdout, stderr, timeout, cwd):
            stdout.write("1 failed, 1 passed")
            xml_path = next(a for a in cmd if "--junitxml" in a).split("=")[1]
            Path(xml_path).write_text(xml_content, encoding="utf-8")
            m = MagicMock()
            m.returncode = 1
            return m

        mock_subproc.side_effect = fake_run
        run = runner.run_tests()
        assert run.total_tests == 2
        assert run.failed == 1
        assert run.passed == 1


class TestRunTestsBoundary:
    """Boundary: 경계값 (CORRECT)."""

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_existence_empty_result(self, mock_subproc, runner):
        """Existence: 테스트 0건 → total_tests=0, completed."""
        xml_content = make_junit_xml([])

        def fake_run(cmd, stdout, stderr, timeout, cwd):
            stdout.write("no tests ran")
            xml_path = next(a for a in cmd if "--junitxml" in a).split("=")[1]
            Path(xml_path).write_text(xml_content, encoding="utf-8")
            m = MagicMock()
            m.returncode = 0
            return m

        mock_subproc.side_effect = fake_run
        run = runner.run_tests()
        assert run.total_tests == 0
        assert run.status == TestRun.STATUS_COMPLETED

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_existence_no_xml(self, mock_subproc, runner):
        """Existence: XML 파일 미생성 → total_tests=0."""
        def fake_run(cmd, stdout, stderr, timeout, cwd):
            stdout.write("")
            # XML 파일 생성 안 함
            m = MagicMock()
            m.returncode = 5  # no tests found
            return m

        mock_subproc.side_effect = fake_run
        run = runner.run_tests()
        assert run.total_tests == 0


class TestRunTestsError:
    """Error: 에러 조건."""

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_timeout(self, mock_subproc, runner):
        """subprocess timeout → status=failed."""
        import subprocess
        mock_subproc.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=1)

        run = runner.run_tests(timeout=1)
        assert run.status == TestRun.STATUS_FAILED

    @patch("app.services.pytest_runner_service.subprocess.run")
    def test_unexpected_exception(self, mock_subproc, runner):
        """예외 발생 → status=failed."""
        mock_subproc.side_effect = OSError("Cannot execute")

        run = runner.run_tests()
        assert run.status == TestRun.STATUS_FAILED


# ============================================================
# 7-3. create_fix_plan_requests() 테스트
# ============================================================

class TestCreateFixPlanRequestsRight:
    """Right: 올바른 결과."""

    def test_creates_llm_requests_for_failed(self, runner, test_db_session, sample_test_run, failed_test_result):
        """failed 1건 → LLM request 1개 생성."""
        sample_test_run.failed = 1
        test_db_session.commit()

        with patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue") as mock_enqueue:
            from app.modules.claude_worker.models.llm_request import LLMRequest
            fake_req = LLMRequest(id=999, caller_type="pytest_fix", caller_id="x", prompt="p", status="pending")
            mock_enqueue.return_value = fake_req

            ids = runner.create_fix_plan_requests(sample_test_run.id)

        assert len(ids) == 1
        assert 999 in ids

    def test_caller_type_is_pytest_fix(self, runner, test_db_session, sample_test_run, failed_test_result):
        """LLM request의 caller_type == 'pytest_fix'."""
        with patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue") as mock_enqueue:
            from app.modules.claude_worker.models.llm_request import LLMRequest
            fake_req = LLMRequest(id=111, caller_type="pytest_fix", caller_id="x", prompt="p", status="pending")
            mock_enqueue.return_value = fake_req
            runner.create_fix_plan_requests(sample_test_run.id)

        call_kwargs = mock_enqueue.call_args[1]
        assert call_kwargs["caller_type"] == "pytest_fix"


class TestCreateFixPlanRequestsBoundary:
    """Boundary: 경계값 (CORRECT)."""

    def test_existence_no_failed(self, runner, test_db_session, sample_test_run):
        """Existence: failed 0건 → 빈 리스트."""
        # failed 없는 passed 결과
        result = TestResult(
            test_run_id=sample_test_run.id,
            test_name="tests/test_foo.py::test_ok",
            status=TestResult.STATUS_PASSED,
            duration_seconds=0.1,
        )
        test_db_session.add(result)
        test_db_session.commit()

        ids = runner.create_fix_plan_requests(sample_test_run.id)
        assert ids == []

    def test_cardinality_multiple_failed(self, runner, test_db_session, sample_test_run):
        """Cardinality: failed 3건 → LLM request 3개."""
        for i in range(3):
            r = TestResult(
                test_run_id=sample_test_run.id,
                test_name=f"tests/test_foo.py::test_{i}",
                status=TestResult.STATUS_FAILED,
                duration_seconds=0.1,
                error_message="err",
            )
            test_db_session.add(r)
        test_db_session.commit()

        with patch("app.modules.claude_worker.services.llm_service.LLMService.enqueue") as mock_enqueue:
            from app.modules.claude_worker.models.llm_request import LLMRequest
            call_count = [0]
            def make_req(*a, **kw):
                call_count[0] += 1
                return LLMRequest(id=call_count[0], caller_type="pytest_fix", caller_id=kw.get("caller_id","x"), prompt="p", status="pending")
            mock_enqueue.side_effect = make_req

            ids = runner.create_fix_plan_requests(sample_test_run.id)

        assert len(ids) == 3

    def test_nonexistent_run_id(self, runner):
        """존재하지 않는 run_id → 빈 리스트."""
        ids = runner.create_fix_plan_requests(99999)
        assert ids == []


# ============================================================
# 7-4. _build_fix_prompt() 테스트
# ============================================================

class TestBuildFixPromptRight:
    """Right: 올바른 결과."""

    def test_prompt_contains_test_name(self, test_db_session, sample_test_run):
        """프롬프트에 test_name 포함."""
        result = TestResult(
            test_run_id=sample_test_run.id,
            test_name="tests/test_foo.py::test_bar",
            status=TestResult.STATUS_FAILED,
            error_message="AssertionError",
            traceback="File test_foo.py line 10",
        )
        test_db_session.add(result)
        test_db_session.commit()

        prompt = PytestRunnerService._build_fix_prompt(result)
        assert "tests/test_foo.py::test_bar" in prompt
        assert "AssertionError" in prompt
        assert "수정" in prompt

    def test_prompt_contains_traceback(self, test_db_session, sample_test_run):
        """프롬프트에 traceback 포함."""
        result = TestResult(
            test_run_id=sample_test_run.id,
            test_name="tests/t.py::t",
            status=TestResult.STATUS_FAILED,
            traceback="long traceback text",
        )
        test_db_session.add(result)
        test_db_session.commit()

        prompt = PytestRunnerService._build_fix_prompt(result)
        assert "long traceback text" in prompt


class TestBuildFixPromptBoundary:
    """Boundary: 경계값 (CORRECT)."""

    def test_existence_none_error_message(self, test_db_session, sample_test_run):
        """Existence: error_message=None → 에러 없이 프롬프트 생성."""
        result = TestResult(
            test_run_id=sample_test_run.id,
            test_name="tests/t.py::t",
            status=TestResult.STATUS_FAILED,
            error_message=None,
            traceback=None,
        )
        test_db_session.add(result)
        test_db_session.commit()

        prompt = PytestRunnerService._build_fix_prompt(result)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_range_long_traceback_truncated(self, test_db_session, sample_test_run):
        """Range: traceback 10000자 → truncate 됨."""
        long_tb = "x" * 10000
        result = TestResult(
            test_run_id=sample_test_run.id,
            test_name="tests/t.py::t",
            status=TestResult.STATUS_FAILED,
            traceback=long_tb,
        )
        test_db_session.add(result)
        test_db_session.commit()

        prompt = PytestRunnerService._build_fix_prompt(result)
        assert "truncated" in prompt


# ============================================================
# 7-5. save_results() / _count_statuses() 테스트
# ============================================================

class TestSaveResults:
    """save_results() 테스트."""

    def test_right_saves_all_records(self, runner, test_db_session, sample_test_run):
        """Right: parsed_results 전체 TestResult로 저장."""
        parsed = [
            {"test_name": "tests/foo.py::test_a", "status": "passed", "duration_seconds": 0.1, "error_message": None, "traceback": None},
            {"test_name": "tests/foo.py::test_b", "status": "failed", "duration_seconds": 0.2, "error_message": "err", "traceback": "tb"},
        ]
        count = runner.save_results(sample_test_run.id, parsed)
        assert count == 2

        saved = test_db_session.query(TestResult).filter(TestResult.test_run_id == sample_test_run.id).all()
        assert len(saved) == 2
        names = {r.test_name for r in saved}
        assert "tests/foo.py::test_a" in names
        assert "tests/foo.py::test_b" in names

    def test_boundary_empty_list(self, runner, test_db_session, sample_test_run):
        """Boundary: 빈 리스트 저장 → 0 반환."""
        count = runner.save_results(sample_test_run.id, [])
        assert count == 0


class TestCountStatuses:
    """_count_statuses() 테스트."""

    def test_right_all_statuses(self):
        """Right: passed/failed/error/skipped 정확히 카운트."""
        parsed = [
            {"status": "passed", "duration_seconds": 0.1},
            {"status": "failed", "duration_seconds": 0.2},
            {"status": "error", "duration_seconds": 0.3},
            {"status": "skipped", "duration_seconds": 0.0},
            {"status": "passed", "duration_seconds": 0.1},
        ]
        counts = PytestRunnerService._count_statuses(parsed)
        assert counts["total"] == 5
        assert counts["passed"] == 2
        assert counts["failed"] == 1
        assert counts["errors"] == 1
        assert counts["skipped"] == 1

    def test_boundary_empty(self):
        """Boundary: 빈 리스트 → 전부 0."""
        counts = PytestRunnerService._count_statuses([])
        assert counts == {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}


# ============================================================
# 7-6. should_run_cron_now() 테스트 (독립 유틸 — playwright 미의존)
# ============================================================

class TestShouldRunCronNow:
    """should_run_cron_now() 독립 유틸 테스트."""

    def test_right_cron_match(self, monkeypatch):
        """Right: 현재 02:00이고 cron '0 2 * * *' → True."""
        now = datetime(2026, 2, 26, 2, 0)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now("0 2 * * *", last_run_at=None)
        assert result is True

    def test_right_json_time_match(self, monkeypatch):
        """Right: JSON {"time": "02:00"} 형식 → True."""
        now = datetime(2026, 2, 26, 2, 2)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now(json.dumps({"time": "02:00"}), last_run_at=None)
        assert result is True

    def test_boundary_time_tolerance(self, monkeypatch):
        """Boundary: 02:04 (±5분 내) → True."""
        now = datetime(2026, 2, 26, 2, 4)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now("0 2 * * *", last_run_at=None)
        assert result is True

    def test_boundary_time_out_of_tolerance(self, monkeypatch):
        """Boundary: 02:06 (>5분) → False."""
        now = datetime(2026, 2, 26, 2, 6)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now("0 2 * * *", last_run_at=None)
        assert result is False

    def test_boundary_already_ran_today(self, monkeypatch):
        """Boundary: last_run_at이 오늘 → False (1일 1회)."""
        now = datetime(2026, 2, 26, 2, 0)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        last_run_at = datetime(2026, 2, 26, 2, 0)
        result = should_run_cron_now("0 2 * * *", last_run_at=last_run_at)
        assert result is False

    def test_boundary_last_run_yesterday(self, monkeypatch):
        """Boundary: last_run_at이 어제 → True."""
        now = datetime(2026, 2, 26, 2, 0)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        last_run_at = datetime(2026, 2, 25, 2, 0)  # 어제
        result = should_run_cron_now("0 2 * * *", last_run_at=last_run_at)
        assert result is True

    def test_boundary_first_run_none(self, monkeypatch):
        """Boundary: last_run_at=None (최초 실행) → True."""
        now = datetime(2026, 2, 26, 2, 1)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now("0 2 * * *", last_run_at=None)
        assert result is True

    def test_error_invalid_schedule_value(self, monkeypatch):
        """Error: 잘못된 schedule_value → False."""
        now = datetime(2026, 2, 26, 2, 0)
        monkeypatch.setattr("app.services.pytest_runner_service.datetime", MagicMock(now=lambda: now))
        result = should_run_cron_now("", last_run_at=None)
        assert result is False
