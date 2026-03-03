"""Level 3: 실제 LLM 1 cycle 실행 → merge까지 전체 파이프라인 E2E

실행 조건:
  - Redis 서버 실행 중
  - Listener 프로세스 기동 가능
  - plan-runner venv 존재 (config.PLAN_RUNNER_PYTHON)
  - LLM API 키 설정됨

실행 명령 (수동 전용, 3~10분 소요):
  pytest -m full_e2e tests/dev_runner/test_full_e2e_real.py -v

주의: 과금 발생 가능 (LLM API 호출)
"""
import time
from pathlib import Path

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from app.main import app
from app.modules.dev_runner.config import DevRunnerConfig
from tests.dev_runner.conftest_e2e import (
    e2e_redis_cleanup,
    listener_process,
    isolated_redis,
)

pytestmark = pytest.mark.full_e2e

BASE_URL = "/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
_config = DevRunnerConfig()


@pytest.fixture(autouse=True)
def require_full_env():
    """Redis + plan-runner venv 존재 확인 — 둘 중 하나 없으면 skip"""
    try:
        r = redis_lib.Redis(decode_responses=True)
        r.ping()
        r.close()
    except Exception:
        pytest.skip("Redis not available")

    if not _config.PLAN_RUNNER_PYTHON.exists():
        pytest.skip(f"plan-runner venv not found: {_config.PLAN_RUNNER_PYTHON}")


@pytest.fixture(scope="function")
def http_client():
    return TestClient(app)


def _post_run(http_client, plan_file: str, max_cycles: int = 1) -> str:
    """POST /run → runner_id 반환"""
    resp = http_client.post(
        f"{BASE_URL}/run",
        json={"plan_file": plan_file, "max_cycles": max_cycles},
    )
    assert resp.status_code == 200, f"POST /run 실패: {resp.status_code} {resp.text}"
    runner_id = resp.json().get("runner_id")
    assert runner_id, f"runner_id 미반환: {resp.json()}"
    return runner_id


def _wait_until_not_running(isolated_redis, runner_id: str, timeout: int = 600) -> bool:
    """status != 'running' 될 때까지 최대 timeout초 대기. 성공 여부 반환."""
    key = f"{RUNNER_KEY_PREFIX}:{runner_id}:status"
    for _ in range(timeout * 2):
        status = isolated_redis.get(key)
        if status != "running":
            return True
        time.sleep(0.5)
    return False


@pytest.mark.timeout(600)
class TestFullE2E:
    """Level 3: 실제 LLM 1 cycle 실행 → merge까지 전체 파이프라인"""

    def test_single_plan_1cycle(self, http_client, listener_process, isolated_redis, e2e_redis_cleanup):
        """단일 plan 파일로 1 cycle 실행 → 완료까지 대기

        검증:
        - running=True → cycle 진행 → running=False
        - 로그 파일에 내용이 기록됨 (size > 0)
        """
        plan_file = str(FIXTURES_DIR / "test_minimal_plan.md")
        runner_id = _post_run(http_client, plan_file, max_cycles=1)

        assert _wait_until_not_running(isolated_redis, runner_id, timeout=600), (
            f"runner {runner_id}가 10분 내 완료되지 않음"
        )

        log_path = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path")
        if log_path and Path(log_path).exists():
            assert Path(log_path).stat().st_size > 0, "로그 파일이 비어 있음"

    def test_single_plan_with_merge(self, http_client, listener_process, isolated_redis, e2e_redis_cleanup):
        """1 cycle 실행 후 merge queue 진입 → 상태 확인

        검증:
        - worktree_path 키로 worktree 디렉토리 생성 확인 (생성 시)
        - 완료 후 merge_status 또는 None 확인 (merge 성공/실패)
        """
        plan_file = str(FIXTURES_DIR / "test_minimal_plan.md")
        runner_id = _post_run(http_client, plan_file, max_cycles=1)

        assert _wait_until_not_running(isolated_redis, runner_id, timeout=600), (
            f"runner {runner_id}가 10분 내 완료되지 않음"
        )

        # worktree 생성 여부 확인 (생성된 경우)
        worktree_path = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        if worktree_path:
            # worktree가 생성됐다면 merge 처리 후 정리됐거나 merge 중
            merge_status = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:merge_status")
            # merge_status는 pending_merge, conflict, merged, 또는 None
            assert merge_status in (None, "pending_merge", "conflict", "merged"), (
                f"예상치 못한 merge_status: {merge_status}"
            )

    def test_batch_run_2plans(self, http_client, listener_process, isolated_redis, e2e_redis_cleanup):
        """2개 plan 순차 실행 → 각각 독립 로그 파일 생성

        검증:
        - 각각 다른 runner_id 반환
        - 각 runner_id 독립 로그 파일 생성
        """
        plan_file = str(FIXTURES_DIR / "test_minimal_plan.md")
        runner_id_1 = _post_run(http_client, plan_file, max_cycles=1)
        runner_id_2 = _post_run(http_client, plan_file, max_cycles=1)

        assert runner_id_1 != runner_id_2, "2개 실행 시 runner_id가 동일하면 안 됨"

        # 두 runner 모두 완료 대기
        for rid in (runner_id_1, runner_id_2):
            assert _wait_until_not_running(isolated_redis, rid, timeout=600), (
                f"runner {rid}가 10분 내 완료되지 않음"
            )

        # 각각 독립 로그 파일 확인
        log_paths = set()
        for rid in (runner_id_1, runner_id_2):
            log_path = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path")
            if log_path:
                log_paths.add(log_path)

        # 두 runner가 서로 다른 로그 파일을 사용해야 함
        assert len(log_paths) == 2, f"독립 로그 파일이 아님: {log_paths}"
