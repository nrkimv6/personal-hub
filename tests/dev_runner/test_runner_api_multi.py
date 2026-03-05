"""멀티 runner API 라우터 HTTP 테스트 (TestClient e2e)

Phase 4 구현 검증: GET /runners, POST /runners/{id}/stop, POST /run runner_id 반환,
GET /logs/recent?runner_id=..., runner_id 누락 시 422
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.dev_runner.schemas import RunnerListItem, RunStatusResponse, LogResponse
from app.modules.dev_runner.services.executor_service import executor_service
from app.modules.dev_runner.routes.runner import router as runner_router
from app.modules.dev_runner.routes.logs import router as logs_router

BASE_URL = "/api/v1/dev-runner"


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """devrunner conftest autouse 오버라이드 — plan_service 의존성 없음"""
    yield


@pytest.fixture
def client():
    """최소 FastAPI 앱 — dev-runner router만 포함"""
    test_app = FastAPI()
    test_app.include_router(runner_router, prefix=BASE_URL)
    test_app.include_router(logs_router, prefix=BASE_URL)
    return TestClient(test_app)


class TestGetRunners:
    """GET /runners — 활성 runner 목록"""

    def test_get_runners_returns_list(self, client):
        """Redis mock → 200 + list 형식 응답"""
        mock_items = [
            RunnerListItem(
                runner_id="t-apimulti-abc1",
                running=True,
                plan_file="test.md",
                engine="claude",
                start_time=datetime.now(),
                pid=1234,
            )
        ]
        with patch.object(executor_service, "get_all_runners", return_value=mock_items):
            resp = client.get(f"{BASE_URL}/runners")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["runner_id"] == "t-apimulti-abc1"
        assert data[0]["running"] is True

    def test_get_runners_redis_unavailable_returns_empty_list(self, client):
        """Redis 미연결 → 200 빈 list (예외 미전파)"""
        with patch.object(executor_service, "get_all_runners", return_value=[]):
            resp = client.get(f"{BASE_URL}/runners")

        assert resp.status_code == 200
        assert resp.json() == []


class TestStopRunner:
    """POST /runners/{runner_id}/stop"""

    def test_stop_existing_runner(self, client):
        """존재하는 runner → 200"""
        with patch.object(executor_service, "stop_dev_runner", new_callable=AsyncMock,
                          return_value={"message": "Stopped successfully"}):
            resp = client.post(f"{BASE_URL}/runners/abc12345/stop")

        assert resp.status_code == 200

    def test_stop_nonexistent_runner_returns_404(self, client):
        """없는 runner_id → 404"""
        from fastapi import HTTPException

        with patch.object(executor_service, "stop_dev_runner", new_callable=AsyncMock,
                          side_effect=HTTPException(status_code=404, detail="Not running")):
            resp = client.post(f"{BASE_URL}/runners/notexist/stop")

        assert resp.status_code == 404


class TestPostRun:
    """POST /run — runner_id 필드 존재 확인"""

    def test_run_response_contains_runner_id(self, client):
        """POST /run 성공 응답 JSON에 runner_id 필드 존재 + 8자 hex"""
        mock_response = RunStatusResponse(
            running=True,
            runner_id="ab12ef34",
            engine="claude",
            listener_alive=True,
            redis_connected=True,
            pid=1234,
            plan_file="test.md",
            start_time=datetime.now(),
            current_cycle=0,
            exit_code=None,
            crashed=False,
            current_plan_name=None,
        )

        with patch.object(executor_service, "start_dev_runner", new_callable=AsyncMock,
                          return_value=mock_response):
            resp = client.post(
                f"{BASE_URL}/run",
                json={"plan_file": "test.md", "engine": "claude"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "runner_id" in data
        assert data["runner_id"] == "ab12ef34"
        assert len(data["runner_id"]) == 8
        assert all(c in "0123456789abcdef" for c in data["runner_id"])


class TestGetRecentLogs:
    """GET /logs/recent?runner_id=...&lines=N"""

    def test_get_recent_logs_with_runner_id(self, client):
        """runner_id 있으면 200 + LogResponse 스키마"""
        from app.modules.dev_runner.services.log_service import log_service

        mock_log = LogResponse(lines=["line1", "line2"], total_lines=2)
        with patch.object(log_service, "tail_log_file", return_value=mock_log):
            resp = client.get(f"{BASE_URL}/logs/recent?runner_id=abc12345&lines=10")

        assert resp.status_code == 200
        data = resp.json()
        assert "lines" in data
        assert "total_lines" in data

    def test_get_recent_logs_missing_runner_id_returns_422(self, client):
        """runner_id 누락 → 422 (Query 필수 파라미터 검증)"""
        resp = client.get(f"{BASE_URL}/logs/recent?lines=10")
        assert resp.status_code == 422

    def test_get_recent_logs_uses_logfile_when_stream_too_small(self, client, tmp_path):
        """T4: stream_log_path 소형(200B 이하) + log_file_path 정상 → log_file 내용 반환
        (stream_log 우선순위 수정 후 HTTP 레벨 동작 검증)
        """
        stream_file = tmp_path / "stream.log"
        stream_file.write_bytes(b"[2026-03-05T20:18:13] START | log_path=...\n")  # 43B

        log_file = tmp_path / "log.log"
        log_file.write_text(
            "[20:18:13] [PLAN-RUNNER] [INFO] Plan-Runner 시작\n"
            "[20:18:13] [PLAN-RUNNER] [DONE] Plan-Runner 종료\n",
            encoding="utf-8",
        )

        from app.modules.dev_runner.services.log_service import log_service

        with patch.object(log_service, "_find_current_log", return_value=log_file):
            resp = client.get(f"{BASE_URL}/logs/recent?runner_id=test-stream-fix&lines=10")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["lines"]) == 2
        assert "Plan-Runner 시작" in data["lines"][0]
