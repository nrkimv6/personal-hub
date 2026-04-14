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

import httpx
import pytest

from app.main import app
from app.modules.dev_runner.config import DevRunnerConfig
from tests.dev_runner.conftest_e2e import (
    e2e_redis_cleanup,
    e2e_worktree_cleanup,
    listener_process,
    isolated_redis,
    TEST_PLAN_FILE,
    TEST_PLAN_FILE_A,
    TEST_PLAN_FILE_B,
)

pytestmark = pytest.mark.integration

BASE_URL = "http://test/api/v1/dev-runner"
RUNNER_KEY_PREFIX = "plan-runner:runners"
_config = DevRunnerConfig()


@pytest.fixture
def cleanup_test_branches():
    """concurrent 테스트 전후 plan 브랜치 정리"""
    from tests.dev_runner.conftest_e2e import _cleanup_test_worktrees

    _cleanup_test_worktrees()
    yield
    _cleanup_test_worktrees()


@pytest.fixture(autouse=True)
def require_plan_runner():
    """plan-runner venv 미존재 시 skip"""
    if not _config.PLAN_RUNNER_PYTHON.exists():
        pytest.skip(f"plan-runner venv not found: {_config.PLAN_RUNNER_PYTHON}")


@pytest.fixture(autouse=True)
async def reset_executor_async_redis():
    """ExecutorService 싱글톤의 async_redis를 현재 event loop에 재초기화.

    pytest-asyncio는 각 테스트마다 새 event loop를 생성하는데,
    모듈 레벨 싱글톤의 async_redis가 이전 loop에 바인딩되어 "Event loop is closed" 오류를 유발함.
    각 테스트 전에 재초기화하여 현재 loop와 매핑시킴.
    """
    import redis.asyncio as aioredis
    from app.modules.dev_runner.services.executor_service import executor_service as svc

    old_redis = svc.async_redis
    svc.async_redis = aioredis.Redis(
        host="localhost",
        port=6379,
        db=15,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=35,
    )
    yield
    try:
        await svc.async_redis.aclose()
    except Exception:
        pass
    svc.async_redis = old_redis


async def _make_client():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _wait_for_runner_status(isolated_redis, runner_id: str, expected: str, timeout: int = 20) -> bool:
    """runner_id의 status 키가 expected 값이 될 때까지 폴링."""
    key = f"{RUNNER_KEY_PREFIX}:{runner_id}:status"
    for _ in range(timeout * 2):
        val = isolated_redis.get(key)
        if val == expected:
            return True
        time.sleep(0.5)
    return False


def _wait_for_redis_key(isolated_redis, key: str, timeout: int = 30) -> str | None:
    """특정 Redis 키가 세팅될 때까지 폴링 후 값 반환. 타임아웃 시 None."""
    for _ in range(timeout * 2):
        val = isolated_redis.get(key)
        if val is not None:
            return val
        time.sleep(0.5)
    return None


async def _post_dry_run(client: httpx.AsyncClient, plan_file: str = TEST_PLAN_FILE) -> str:
    """dry_run POST 실행 → runner_id 반환."""
    resp = await client.post(
        "/api/v1/dev-runner/run",
        json={
            "engine": "gemini",
            "plan_file": plan_file,
            "dry_run": True,
            "test_source": "test_runner_dry_run",
        },
    )
    assert resp.status_code == 200, f"POST /run 실패: {resp.status_code} {resp.text}"
    runner_id = resp.json().get("runner_id")
    assert runner_id, f"runner_id 미반환: {resp.json()}"
    return runner_id


class TestRunnerDryRun:
    """Level 2: dry_run으로 Runner 기동/종료 파이프라인 검증"""

    async def test_dry_run_lifecycle(self, listener_process, isolated_redis, e2e_redis_cleanup, e2e_worktree_cleanup):
        """POST /run (dry_run) → running=True → stop → running=False"""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            runner_id = await _post_dry_run(client)

            assert _wait_for_runner_status(isolated_redis, runner_id, "running", timeout=30), (
                f"runner {runner_id}가 30초 내 running 상태가 되지 않음"
            )

            stop_resp = await client.post(
                "/api/v1/dev-runner/stop", json={"runner_id": runner_id}
            )
            assert stop_resp.status_code == 200, f"POST /stop 실패: {stop_resp.text}"

        # running 해제 대기
        stopped = False
        for _ in range(20):
            status = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status")
            if status is None or status == "stopped":
                stopped = True
                break
            time.sleep(0.5)
        assert stopped, f"runner {runner_id}가 10초 내 stopped 상태가 되지 않음"

    async def test_dry_run_redis_keys(self, listener_process, isolated_redis, e2e_redis_cleanup, e2e_worktree_cleanup):
        """dry_run 실행 후 per-runner Redis 키 (status/pid/plan_file/start_time) 세팅 확인"""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            runner_id = await _post_dry_run(client)

            assert _wait_for_runner_status(isolated_redis, runner_id, "running", timeout=30), (
                f"runner {runner_id}가 30초 내 running 상태가 되지 않음"
            )

            pid = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid")
            plan_file = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
            start_time = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:start_time")

            assert pid is not None, "pid 키 미세팅"
            assert plan_file is not None, "plan_file 키 미세팅"
            assert start_time is not None, "start_time 키 미세팅"

            # 검증 후 정리
            await client.post("/api/v1/dev-runner/stop", json={"runner_id": runner_id})

    async def test_dry_run_log_file_created(self, listener_process, isolated_redis, e2e_redis_cleanup, e2e_worktree_cleanup):
        """dry_run 실행 후 stream_log_path 파일 생성 확인"""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            runner_id = await _post_dry_run(client)

            assert _wait_for_runner_status(isolated_redis, runner_id, "running", timeout=40), (
                f"runner {runner_id}가 40초 내 running 상태가 되지 않음"
            )

            # stream_log_path는 plan-runner 내부 _open_log() 호출 후 설정됨.
            # status=running 직후에는 아직 미설정 상태일 수 있으므로 별도 폴링 필요.
            log_path = _wait_for_redis_key(
                isolated_redis, f"{RUNNER_KEY_PREFIX}:{runner_id}:stream_log_path", timeout=30
            )
            assert log_path is not None, "stream_log_path 키 미세팅 (30초 대기)"
            assert Path(log_path).exists(), f"로그 파일 미생성: {log_path}"

            # 검증 후 정리
            await client.post("/api/v1/dev-runner/stop", json={"runner_id": runner_id})

    async def test_concurrent_dry_run(self, listener_process, isolated_redis, e2e_redis_cleanup, e2e_worktree_cleanup, cleanup_test_branches):
        """2개 동시 dry_run 실행 → 각각 독립 runner_id + 상태

        서로 다른 plan_file 사용 — 동일 plan_file이면 WorktreeManager 브랜치명 충돌 발생
        """
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            runner_id_1 = await _post_dry_run(client, plan_file=TEST_PLAN_FILE_A)
            runner_id_2 = await _post_dry_run(client, plan_file=TEST_PLAN_FILE_B)

            assert runner_id_1 != runner_id_2, "동시 실행 시 runner_id가 동일하면 안 됨"

            # 두 runner 모두 running 대기
            # Listener가 명령을 순차 처리하므로 첫 번째 runner 시작 후 두 번째 처리 — 최대 60초
            for rid in (runner_id_1, runner_id_2):
                assert _wait_for_runner_status(isolated_redis, rid, "running", timeout=60), (
                    f"runner {rid}가 60초 내 running 상태가 되지 않음"
                )

            for rid in (runner_id_1, runner_id_2):
                assert isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{rid}:pid") is not None, (
                    f"runner {rid} pid 키 없음"
                )

            # 검증 후 정리
            for rid in (runner_id_1, runner_id_2):
                await client.post("/api/v1/dev-runner/stop", json={"runner_id": rid})

    async def test_accepted_started_ordering(self, listener_process, isolated_redis, e2e_redis_cleanup, e2e_worktree_cleanup):
        """accepted_at <= started_at 순서 보장 TC

        accepted_at: start_plan_runner()에서 lpush 직후 저장 (listener 처리 시점)
        started_at: _launch_plan_runner_process()에서 프로세스 spawn 직후 저장
        → accepted_at이 먼저 기록되고, started_at이 이후에 기록되어야 함
        """
        from datetime import datetime
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            runner_id = await _post_dry_run(client)

            # started_at까지 관측될 때까지 대기 (프로세스 spawn 후 저장)
            started_at_str = _wait_for_redis_key(
                isolated_redis, f"{RUNNER_KEY_PREFIX}:{runner_id}:started_at", timeout=30
            )
            assert started_at_str is not None, f"started_at 미관찰 (runner_id={runner_id}, 30초)"

            accepted_at_str = isolated_redis.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:accepted_at")
            assert accepted_at_str is not None, f"accepted_at 미관찰 (runner_id={runner_id})"

            try:
                accepted_at_dt = datetime.fromisoformat(accepted_at_str)
                started_at_dt = datetime.fromisoformat(started_at_str)
            except ValueError as e:
                raise AssertionError(f"timestamp 파싱 실패: {e}") from e

            assert accepted_at_dt <= started_at_dt, (
                f"accepted_at({accepted_at_str}) > started_at({started_at_str}): "
                "관측 순서 계약 위반"
            )

            # 정리
            await client.post("/api/v1/dev-runner/stop", json={"runner_id": runner_id})
