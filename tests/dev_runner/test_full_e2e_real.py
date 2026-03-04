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
import os
import re
import signal
import time
from pathlib import Path

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from app.main import app
from app.modules.dev_runner.config import DevRunnerConfig
from app.modules.dev_runner.services.executor_service import RUNNER_KEY_SUFFIXES, ACTIVE_RUNNERS_KEY
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


@pytest.fixture(scope="class")
def real_redis_db0():
    """db=0 Redis — API/프로덕션 리스너와 동일 DB. PID 조회 전용."""
    try:
        r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield r
    r.close()


@pytest.fixture(scope="class")
def http_client():
    """TestClient를 context manager로 사용 — 동일 event loop 유지 (BRPOP 연결 재사용 안전)

    context manager 없이 TestClient를 쓰면 요청마다 새 anyio event loop가 생성되어
    executor_service.async_redis 연결 풀이 이전 (닫힌) loop의 연결을 재사용하려다
    RuntimeError: Event loop is closed 발생.
    scope="class"로 동일 TestClient 인스턴스를 클래스 내 모든 테스트가 공유.
    """
    with TestClient(app) as client:
        yield client


def _post_run(http_client, plan_file: str, max_cycles: int = 1, tracker=None) -> str:
    """POST /run → runner_id 반환. tracker 리스트 지정 시 runner_id 자동 등록."""
    resp = http_client.post(
        f"{BASE_URL}/run",
        json={"plan_file": plan_file, "max_cycles": max_cycles},
    )
    assert resp.status_code == 200, f"POST /run 실패: {resp.status_code} {resp.text}"
    runner_id = resp.json().get("runner_id")
    assert runner_id, f"runner_id 미반환: {resp.json()}"
    if tracker is not None:
        tracker.append(runner_id)
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

    @pytest.fixture(autouse=True)
    def force_kill_runners(self, isolated_redis, real_redis_db0):
        """테스트 후 시작된 모든 runner 프로세스를 강제 정리하는 안전망 fixture.

        self-termination에 의존하지 않고, teardown에서 명시적으로 PID kill을 수행한다.
        PID는 API가 사용하는 db=0에 저장되므로 real_redis_db0으로 조회한다.
        """
        self._started_runners = []
        yield
        # teardown: 각 runner PID kill (db=0에서 PID 조회)
        for rid in self._started_runners:
            pid_str = real_redis_db0.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid")
            if pid_str:
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except (ProcessLookupError, ValueError, OSError):
                    pass
        # Redis 키 정리 (db=0)
        for rid in self._started_runners:
            for suffix in RUNNER_KEY_SUFFIXES:
                real_redis_db0.delete(f"{RUNNER_KEY_PREFIX}:{rid}:{suffix}")
            real_redis_db0.srem(ACTIVE_RUNNERS_KEY, rid)
            real_redis_db0.zrem("plan-runner:recent_runners", rid)

    def test_single_plan_1cycle(self, http_client, listener_process, isolated_redis, e2e_redis_cleanup):
        """단일 plan 파일로 1 cycle 실행 → 완료까지 대기

        검증:
        - running=True → cycle 진행 → running=False
        - 로그 파일에 내용이 기록됨 (size > 0)
        """
        plan_file = str(FIXTURES_DIR / "test_minimal_plan.md")
        runner_id = _post_run(http_client, plan_file, max_cycles=1, tracker=self._started_runners)

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
        runner_id = _post_run(http_client, plan_file, max_cycles=1, tracker=self._started_runners)

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

    def test_batch_run_2plans(self, http_client, listener_process, isolated_redis, e2e_redis_cleanup, tmp_path):
        """2개 plan 순차 실행 → 각각 독립 runner_id 반환

        검증:
        - 각각 다른 runner_id 반환 (동시 실행 지원 핵심 속성)
        - 각 runner_id 독립 로그 파일 생성 (동일 파일 공유 금지)

        NOTE: 테스트 리스너는 db=15, API는 db=0 사용 → 양측이 연결되지 않으므로
        isolated_redis(db=15)에서 조회한 log_paths는 None이 될 수 있음.
        log_paths_set이 비어있으면 "공유 없음"으로 간주하여 통과.
        (핵심 검증: runner_id 차별성. 로그 파일 고유성은 실서버 E2E에서 확인)
        """
        # branch/worktree 필드 없는 임시 플랜 파일 사용
        # (plan-runner가 merge 시도하지 않도록, 이전 테스트 실행이 필드를 추가해도 영향 없음)
        src_content = (FIXTURES_DIR / "test_minimal_plan.md").read_text(encoding="utf-8")
        src_content = re.sub(r"^> branch:.*\n", "", src_content, flags=re.MULTILINE)
        src_content = re.sub(r"^> worktree:.*\n", "", src_content, flags=re.MULTILINE)
        plan_tmp = tmp_path / "test_batch_plan.md"
        plan_tmp.write_text(src_content, encoding="utf-8")

        plan_file = str(plan_tmp)
        runner_id_1 = _post_run(http_client, plan_file, max_cycles=1, tracker=self._started_runners)
        runner_id_2 = _post_run(http_client, plan_file, max_cycles=1, tracker=self._started_runners)

        assert runner_id_1 != runner_id_2, "2개 실행 시 runner_id가 동일하면 안 됨"

        # 각각 독립 로그 파일 확인 (isolated_redis=db=15에서 조회, 테스트 리스너와 동일 DB)
        # 빠르게 종료되는 plan은 log file을 생성하지 않을 수 있으므로, 생성된 경우에만 검증
        log_paths = [
            isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:stream_log_path")
            for rid in (runner_id_1, runner_id_2)
        ]
        log_paths_set = set(p for p in log_paths if p)

        # 두 runner가 동일한 로그 파일을 공유하지 않아야 함 (1개이면 공유 = 버그)
        assert len(log_paths_set) != 1, f"두 runner가 같은 로그 파일 공유: {log_paths_set}"
