"""Phase T4: heartbeat 머지 보호 조건 HTTP 통합 테스트

대상 수정:
  - heartbeat L2576: MERGE_ACTIVE_STATUSES 상수 사용 (pre_merge/resolving/testing/fixing 커버)
  - _monitor_pid_until_exit L334: reason="heartbeat_pid_exit"

검증 범위:
  T4-1: GET /api/v1/dev-runner/runners — merge_status 필드가 신규 보호 상태값
        (pre_merge, resolving, testing, fixing)을 올바르게 직렬화/반환하는지 확인.
        heartbeat cleanup이 이들 상태를 보호하려면, API가 이 값들을 그대로 노출해야 함.

  T4-2: cleanup guard + HTTP 상태 연계 — cleanup 거부 후 /runners API가 runner를
        "stopped"가 아닌 "running" 상태로 계속 보고하는지 확인.
        (listener 모듈 직접 호출 + TestClient HTTP 조회 결합)
"""

import pytest
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from fastapi.testclient import TestClient
from app.modules.dev_runner.schemas import RunnerListItem

import fakeredis
import fakeredis.aioredis

from tests.dev_runner._path_helpers import get_listener_script_path, skip_if_missing

pytestmark = pytest.mark.http

BASE_URL = "/api/v1/dev-runner"

RUNNER_KEY_PREFIX = "plan-runner:runners"
MERGE_ACTIVE_STATUSES = ("pre_merge", "queued", "merging", "pending_merge", "resolving", "testing", "fixing")


def _build_test_client() -> TestClient:
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


# ========== 픽스처 ==========

@pytest.fixture(scope="module")
def client():
    return _build_test_client()


@pytest.fixture(autouse=True)
def dev_runner_config_isolation():
    """devrunner conftest autouse 오버라이드"""
    yield


@pytest.fixture(scope="module")
def listener_mod():
    script_path = get_listener_script_path()
    skip_if_missing(script_path, "Listener script")
    spec = importlib.util.spec_from_file_location("dev_runner_cmd_listener_t4", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ========== T4-1: /runners API merge_status 직렬화 ==========

class TestRunnersApiMergeStatusField:
    """GET /api/v1/dev-runner/runners 가 MERGE_ACTIVE_STATUSES 전체 값을 올바르게 반환하는지 검증.

    heartbeat cleanup이 pre_merge/resolving/testing/fixing를 보호하므로,
    이 값들이 Redis에 남아 있고 API가 그대로 노출해야 실제 보호 효과가 의미 있음.
    """

    def test_listener_fixture_uses_repo_local_script_right(self, listener_mod):
        """R: listener fixture가 현재 checkout의 scripts 경로를 로드해야 함"""
        assert Path(listener_mod.__file__).resolve() == get_listener_script_path().resolve()

    @pytest.mark.parametrize("merge_status", list(MERGE_ACTIVE_STATUSES))
    def test_runners_api_exposes_merge_status_right(self, client, merge_status):
        """R: get_all_runners가 각 MERGE_ACTIVE_STATUSES 값을 반환하면 /runners API도 그대로 전달"""
        runner_id = f"t4-runner-{merge_status}"
        mock_runner = RunnerListItem(
            runner_id=runner_id,
            running=True,
            merge_status=merge_status,
            plan_file="test.md",
            engine="claude",
            pid=12345,
            start_time=datetime.now(),
        )

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=[mock_runner],
        ):
            r = client.get(f"{BASE_URL}/runners")

        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["runner_id"] == runner_id
        assert data[0]["merge_status"] == merge_status, (
            f"merge_status='{merge_status}'가 API 응답에 그대로 포함되어야 함 "
            f"(실제: {data[0].get('merge_status')})"
        )
        assert data[0]["running"] is True

    def test_runners_api_merge_status_none_right(self, client):
        """R: merge_status=None이면 API 응답에서 null로 반환 (필드 자체는 존재)"""
        mock_runner = RunnerListItem(
            runner_id="t4-runner-no-merge",
            running=True,
            merge_status=None,
        )

        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=[mock_runner],
        ):
            r = client.get(f"{BASE_URL}/runners")

        assert r.status_code == 200
        data = r.json()
        assert data[0]["merge_status"] is None

    def test_runners_api_empty_list_right(self, client):
        """B: runner 없으면 빈 배열 반환 (기존 동작 보존)"""
        with patch(
            "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
            new_callable=AsyncMock,
            return_value=[],
        ):
            r = client.get(f"{BASE_URL}/runners")

        assert r.status_code == 200
        assert r.json() == []


# ========== T4-2: cleanup guard → HTTP 상태 연계 ==========

class TestCleanupGuardHttpStatusIntegration:
    """heartbeat cleanup 거부 후 /runners API가 runner를 running으로 보고하는지 검증.

    시나리오:
      1. listener 모듈에서 runner를 _running_processes에 등록
      2. fakeredis에 merge_status="pre_merge" 설정
      3. heartbeat_dead_process reason으로 _cleanup_process_state 호출 (cleanup 거부 예상)
      4. /runners API mock에 cleanup 거부 결과를 반영 → running=True 확인
    """

    def test_cleanup_guard_runner_stays_running_pre_merge_right(self, client, listener_mod):
        """R: merge_status="pre_merge" → cleanup 거부 → /runners API가 running=True 반환"""
        runner_id = "t4-guard-pre-merge"
        fr = fakeredis.FakeRedis(decode_responses=True)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", "pre_merge")
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                listener_mod._cleanup_process_state(runner_id, fr, reason="heartbeat_dead_process")

            # cleanup 거부 확인 — _running_processes에서 제거되지 않았어야 함
            assert runner_id in listener_mod._running_processes

            # HTTP API: runner가 cleanup되지 않았으므로 running=True로 보고되어야 함
            mock_runner = RunnerListItem(
                runner_id=runner_id,
                running=True,
                merge_status="pre_merge",
            )
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
                new_callable=AsyncMock,
                return_value=[mock_runner],
            ):
                r = client.get(f"{BASE_URL}/runners")

            assert r.status_code == 200
            data = r.json()
            assert data[0]["running"] is True
            assert data[0]["merge_status"] == "pre_merge"

        finally:
            listener_mod._running_processes.pop(runner_id, None)

    def test_cleanup_proceeds_no_merge_signal_runner_stopped_right(self, client, listener_mod):
        """R: merge 시그널 없음 → cleanup 진행 → /runners API가 빈 배열 반환 (running runner 없음)"""
        runner_id = "t4-guard-no-signal"
        fr = fakeredis.FakeRedis(decode_responses=True)
        # merge 키 없음
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                listener_mod._cleanup_process_state(runner_id, fr, reason="heartbeat_dead_process")

            # cleanup 진행 확인
            assert runner_id not in listener_mod._running_processes

            # HTTP API: cleanup 후 running runner 없음
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
                new_callable=AsyncMock,
                return_value=[],
            ):
                r = client.get(f"{BASE_URL}/runners")

            assert r.status_code == 200
            assert r.json() == []

        finally:
            listener_mod._running_processes.pop(runner_id, None)

    @pytest.mark.parametrize("merge_status", ["resolving", "testing", "fixing"])
    def test_cleanup_guard_extended_statuses_runner_stays_running_right(self, client, listener_mod, merge_status):
        """R: 신규 보호 상태 (resolving/testing/fixing) → cleanup 거부 → running=True"""
        runner_id = f"t4-guard-{merge_status}"
        fr = fakeredis.FakeRedis(decode_responses=True)
        fr.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status", merge_status)
        listener_mod._running_processes[runner_id] = MagicMock()

        try:
            with patch.object(listener_mod, "WorktreeManager"):
                listener_mod._cleanup_process_state(runner_id, fr, reason="heartbeat_dead_process")

            assert runner_id in listener_mod._running_processes, (
                f"merge_status='{merge_status}'에서 cleanup이 거부되어야 함"
            )

            mock_runner = RunnerListItem(
                runner_id=runner_id,
                running=True,
                merge_status=merge_status,
            )
            with patch(
                "app.modules.dev_runner.routes.runner.executor_service.get_all_runners",
                new_callable=AsyncMock,
                return_value=[mock_runner],
            ):
                r = client.get(f"{BASE_URL}/runners")

            assert r.status_code == 200
            data = r.json()
            assert data[0]["running"] is True
            assert data[0]["merge_status"] == merge_status

        finally:
            listener_mod._running_processes.pop(runner_id, None)
