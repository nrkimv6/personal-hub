"""Level 2: dry_run으로 Runner 기동/종료 파이프라인 검증

실행 조건:
  - Redis 서버 실행 중
  - Listener 프로세스 기동 가능
  - plan-runner venv 존재 (config.PLAN_RUNNER_PYTHON)

실행 명령:
  pytest -m integration tests/dev_runner/test_runner_dry_run.py -v
"""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.dev_runner.config import DevRunnerConfig
from tests.dev_runner.conftest_e2e import (
    e2e_redis_cleanup,
    listener_process,
    real_redis,
)

pytestmark = pytest.mark.integration

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
_config = DevRunnerConfig()


@pytest.fixture(autouse=True)
def require_plan_runner():
    """plan-runner venv 미존재 시 skip"""
    if not _config.PLAN_RUNNER_PYTHON.exists():
        pytest.skip(f"plan-runner venv not found: {_config.PLAN_RUNNER_PYTHON}")


@pytest.fixture(scope="module")
def http_client():
    """TestClient (모듈 범위 — Listener와 함께 재사용)"""
    return TestClient(app)


def _wait_for_runner_status(real_redis, runner_id: str, expected: str, timeout: int = 20) -> bool:
    """runner_id의 status 키가 expected 값이 될 때까지 폴링. 성공 여부 반환."""
    key = f"{RUNNER_KEY_PREFIX}:{runner_id}:status"
    for _ in range(timeout * 2):
        val = real_redis.get(key)
        if val == expected:
            return True
        time.sleep(0.5)
    return False


def _post_dry_run(http_client, plan_file: str = "docs/plan/test_e2e_plan.md") -> str:
    """dry_run POST 실행 → runner_id 반환. 실패 시 pytest.fail."""
    resp = http_client.post(
        f"{BASE_URL}/run",
        json={"engine": "gemini", "plan_file": plan_file, "dry_run": True},
    )
    assert resp.status_code == 200, f"POST /run 실패: {resp.status_code} {resp.text}"
    runner_id = resp.json().get("runner_id")
    assert runner_id, f"runner_id 미반환: {resp.json()}"
    return runner_id


class TestRunnerDryRun:
    """Level 2: dry_run으로 Runner 기동/종료 파이프라인 검증"""

    def test_dry_run_lifecycle(self, http_client, listener_process, real_redis, e2e_redis_cleanup):
        """POST /run (dry_run) → running=True → stop → running=False"""
        runner_id = _post_dry_run(http_client)

        assert _wait_for_runner_status(real_redis, runner_id, "running", timeout=20), (
            f"runner {runner_id}가 20초 내 running 상태가 되지 않음"
        )

        # stop 요청
        stop_resp = http_client.post(f"{BASE_URL}/stop", json={"runner_id": runner_id})
        assert stop_resp.status_code == 200, f"POST /stop 실패: {stop_resp.text}"

        # running 해제 대기 (status 키 삭제 또는 stopped)
        stopped = False
        for _ in range(20):
            status = real_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            if status is None or status == "stopped":
                stopped = True
                break
            time.sleep(0.5)
        assert stopped, f"runner {runner_id}가 10초 내 stopped 상태가 되지 않음"

    def test_dry_run_redis_keys(self, http_client, listener_process, real_redis, e2e_redis_cleanup):
        """dry_run 실행 후 per-runner Redis 키 (status/pid/plan_file/start_time) 세팅 확인"""
        runner_id = _post_dry_run(http_client)

        assert _wait_for_runner_status(real_redis, runner_id, "running", timeout=20), (
            f"runner {runner_id}가 20초 내 running 상태가 되지 않음"
        )

        pid = real_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
        plan_file = real_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        start_time = real_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")

        assert pid is not None, "pid 키 미세팅"
        assert plan_file is not None, "plan_file 키 미세팅"
        assert start_time is not None, "start_time 키 미세팅"

    def test_dry_run_log_file_created(self, http_client, listener_process, real_redis, e2e_redis_cleanup):
        """dry_run 실행 후 stream_log_path 파일 생성 확인"""
        runner_id = _post_dry_run(http_client)

        assert _wait_for_runner_status(real_redis, runner_id, "running", timeout=20), (
            f"runner {runner_id}가 20초 내 running 상태가 되지 않음"
        )

        log_path = real_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        assert log_path is not None, "stream_log_path 키 미세팅"
        assert Path(log_path).exists(), f"로그 파일 미생성: {log_path}"

    def test_concurrent_dry_run(self, http_client, listener_process, real_redis, e2e_redis_cleanup):
        """2개 동시 dry_run 실행 → 각각 독립 runner_id + 상태"""
        runner_id_1 = _post_dry_run(http_client)
        runner_id_2 = _post_dry_run(http_client)

        assert runner_id_1 != runner_id_2, "동시 실행 시 runner_id가 동일하면 안 됨"

        # 각각 running 상태 확인
        for rid in (runner_id_1, runner_id_2):
            assert _wait_for_runner_status(real_redis, rid, "running", timeout=20), (
                f"runner {rid}가 20초 내 running 상태가 되지 않음"
            )

        # 각각 독립 Redis 키 존재 확인
        for rid in (runner_id_1, runner_id_2):
            assert real_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid") is not None, (
                f"runner {rid} pid 키 없음"
            )
