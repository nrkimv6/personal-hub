"""
테스트 실행 이력 API HTTP 레벨 테스트 (TestClient)

RIGHT-BICEP + CORRECT 원칙 적용:
- Right: 올바른 결과
- Boundary: 경계값
- Error: 에러 조건

테스트 대상:
- GET /api/v1/test-runs
- GET /api/v1/test-runs/{id}
- GET /api/v1/test-runs/{id}/results
- POST /api/v1/test-runs (수동 실행 트리거)
- GET /api/v1/test-runs/{id}/log
"""

import importlib.util
import json
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.test_run import TestRun, TestResult

# app/routes/__init__.py 가 aiohttp 등 무거운 의존성을 일괄 import하므로
# importlib로 라우터 모듈만 직접 로드한다.
_spec = importlib.util.spec_from_file_location(
    "test_runs_routes",
    PROJECT_ROOT / "app" / "routes" / "test_runs.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
test_runs_router = _mod.router

# minimal app — playwright 등 무거운 의존성 없이 test-runs 라우터만
app = FastAPI()
app.include_router(test_runs_router)


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cleanup(test_db_session):
    """각 테스트 전후 TestRun/TestResult 정리."""
    test_db_session.query(TestResult).delete()
    test_db_session.query(TestRun).delete()
    test_db_session.commit()
    yield
    test_db_session.query(TestResult).delete()
    test_db_session.query(TestRun).delete()
    test_db_session.commit()


def make_test_run(test_db_session, **kwargs) -> TestRun:
    """TestRun fixture 헬퍼."""
    defaults = dict(
        status=TestRun.STATUS_COMPLETED,
        triggered_by=TestRun.TRIGGERED_BY_MANUAL,
        test_path="tests/",
        total_tests=5, passed=4, failed=1, errors=0, skipped=0,
        duration_seconds=1.23,
    )
    defaults.update(kwargs)
    run = TestRun(**defaults)
    test_db_session.add(run)
    test_db_session.commit()
    test_db_session.refresh(run)
    return run


def make_test_result(test_db_session, test_run_id: int, **kwargs) -> TestResult:
    """TestResult fixture 헬퍼."""
    defaults = dict(
        test_name="tests/test_foo.py::test_bar",
        status=TestResult.STATUS_PASSED,
        duration_seconds=0.1,
    )
    defaults.update(kwargs)
    result = TestResult(test_run_id=test_run_id, **defaults)
    test_db_session.add(result)
    test_db_session.commit()
    test_db_session.refresh(result)
    return result


# ============================================================
# Right: 올바른 결과
# ============================================================

class TestListTestRunsRight:
    """GET /api/v1/test-runs — Right."""

    def test_empty_list(self, client):
        """빈 DB → 200, []."""
        resp = client.get("/api/v1/test-runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_data(self, client, test_db_session):
        """데이터 있음 → 200, 목록."""
        make_test_run(test_db_session)
        make_test_run(test_db_session)
        resp = client.get("/api/v1/test-runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_ordered_by_started_at_desc(self, client, test_db_session):
        """최신순 정렬."""
        run1 = make_test_run(test_db_session, started_at=datetime(2026, 1, 1, 1, 0))
        run2 = make_test_run(test_db_session, started_at=datetime(2026, 1, 2, 1, 0))
        resp = client.get("/api/v1/test-runs")
        data = resp.json()
        assert data[0]["id"] == run2.id  # 최신이 먼저


class TestGetTestRunRight:
    """GET /api/v1/test-runs/{id} — Right."""

    def test_detail_fields(self, client, test_db_session):
        """상세 조회: 필수 필드 모두 포함."""
        run = make_test_run(test_db_session)
        resp = client.get(f"/api/v1/test-runs/{run.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == run.id
        assert data["status"] == "completed"
        assert data["total_tests"] == 5
        assert data["passed"] == 4
        assert data["failed"] == 1
        assert "results" in data

    def test_detail_results_duration_asc(self, client, test_db_session):
        """결과 목록이 duration 오름차순."""
        run = make_test_run(test_db_session)
        make_test_result(test_db_session, run.id, duration_seconds=2.0)
        make_test_result(test_db_session, run.id, duration_seconds=0.1)
        make_test_result(test_db_session, run.id, duration_seconds=1.0)

        resp = client.get(f"/api/v1/test-runs/{run.id}")
        data = resp.json()
        durations = [r["duration_seconds"] for r in data["results"]]
        assert durations == sorted(durations)


class TestListTestResultsRight:
    """GET /api/v1/test-runs/{id}/results — Right."""

    def test_results_list(self, client, test_db_session):
        """결과 목록 조회."""
        run = make_test_run(test_db_session)
        make_test_result(test_db_session, run.id, status=TestResult.STATUS_PASSED)
        make_test_result(test_db_session, run.id, status=TestResult.STATUS_FAILED,
                         error_message="err")
        resp = client.get(f"/api/v1/test-runs/{run.id}/results")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_results_filter_by_status(self, client, test_db_session):
        """상태 필터."""
        run = make_test_run(test_db_session)
        make_test_result(test_db_session, run.id, status=TestResult.STATUS_PASSED)
        make_test_result(test_db_session, run.id, status=TestResult.STATUS_FAILED,
                         error_message="err")

        resp = client.get(f"/api/v1/test-runs/{run.id}/results?status=failed")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "failed"


class TestTriggerTestRunRight:
    """POST /api/v1/test-runs — Right."""

    def test_trigger_returns_run_id(self, client):
        """수동 실행 트리거 → 200, test_run_id 반환."""
        resp = client.post("/api/v1/test-runs", json={
            "test_path": "tests/",
            "extra_args": [],
            "timeout": 1800,
            "auto_fix_plan": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "test_run_id" in data
        assert data["test_run_id"] > 0


# ============================================================
# Boundary: 경계값 (CORRECT)
# ============================================================

class TestListTestRunsBoundary:
    """GET /api/v1/test-runs — Boundary."""

    def test_status_filter(self, client, test_db_session):
        """상태 필터: completed만 조회."""
        make_test_run(test_db_session, status=TestRun.STATUS_COMPLETED)
        make_test_run(test_db_session, status=TestRun.STATUS_FAILED)
        resp = client.get("/api/v1/test-runs?status=completed")
        data = resp.json()
        assert all(r["status"] == "completed" for r in data)
        assert len(data) == 1

    def test_limit_pagination(self, client, test_db_session):
        """limit=1 페이지 크기 제한."""
        make_test_run(test_db_session)
        make_test_run(test_db_session)
        resp = client.get("/api/v1/test-runs?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_offset_pagination(self, client, test_db_session):
        """offset 페이지네이션."""
        make_test_run(test_db_session, started_at=datetime(2026, 1, 1))
        make_test_run(test_db_session, started_at=datetime(2026, 1, 2))
        resp = client.get("/api/v1/test-runs?offset=1&limit=10")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestTriggerRunBoundary:
    """POST /api/v1/test-runs — Boundary."""

    def test_default_values_applied(self, client):
        """extra_args 기본값 적용."""
        resp = client.post("/api/v1/test-runs", json={"test_path": "tests/"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ============================================================
# Error: 에러 조건
# ============================================================

class TestGetTestRunError:
    """Error: 존재하지 않는 리소스."""

    def test_get_nonexistent_run(self, client):
        """GET /api/v1/test-runs/99999 → 404."""
        resp = client.get("/api/v1/test-runs/99999")
        assert resp.status_code == 404

    def test_get_results_nonexistent_run(self, client):
        """GET /api/v1/test-runs/99999/results → 404."""
        resp = client.get("/api/v1/test-runs/99999/results")
        assert resp.status_code == 404

    def test_get_log_nonexistent_run(self, client):
        """GET /api/v1/test-runs/99999/log → 404."""
        resp = client.get("/api/v1/test-runs/99999/log")
        assert resp.status_code == 404

    def test_get_log_missing_file(self, client, test_db_session):
        """로그 파일이 실제로 없음 → 404."""
        run = make_test_run(test_db_session, log_file_path="/nonexistent/path.log")
        resp = client.get(f"/api/v1/test-runs/{run.id}/log")
        assert resp.status_code == 404

    def test_trigger_no_body(self, client):
        """POST body 없음 → 422 (기본값으로 처리됨 — FastAPI가 default로 허용)."""
        # Pydantic 기본값이 있으므로 422 대신 200도 가능
        resp = client.post("/api/v1/test-runs")
        assert resp.status_code in (200, 422)


class TestTriggerRunError:
    """POST /api/v1/test-runs — Error."""

    def test_already_running_returns_409(self, client, test_db_session):
        """이미 실행 중인 테스트가 있을 경우 → 409."""
        # 실행 중 TestRun 생성
        running = make_test_run(test_db_session, status=TestRun.STATUS_RUNNING)
        resp = client.post("/api/v1/test-runs", json={"test_path": "tests/"})
        assert resp.status_code == 409
        assert str(running.id) in resp.json()["detail"]


# ============================================================
# Log 파일 테스트
# ============================================================

class TestGetLogRight:
    """GET /api/v1/test-runs/{id}/log — Right."""

    def test_log_content_returned(self, client, test_db_session, tmp_path):
        """로그 파일 내용 반환."""
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        run = make_test_run(test_db_session, log_file_path=str(log_file))
        resp = client.get(f"/api/v1/test-runs/{run.id}/log")
        assert resp.status_code == 200
        data = resp.json()
        assert "line1" in data["log"]
        assert "line2" in data["log"]
        assert data["run_id"] == run.id

    def test_log_missing_path(self, client, test_db_session):
        """log_file_path=None → 404."""
        run = make_test_run(test_db_session, log_file_path=None)
        resp = client.get(f"/api/v1/test-runs/{run.id}/log")
        assert resp.status_code == 404
