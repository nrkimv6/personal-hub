"""dev_runner E2E 테스트 공유 fixture

실제 Redis + Listener 프로세스를 사용하는 통합/E2E 테스트용 fixture.
fakeredis 기반 단위 테스트와 분리하여 관리.

사용:
    from tests.dev_runner.conftest_e2e import real_redis, listener_process, test_plan_file
"""
import json
import subprocess
import time
from pathlib import Path

import pytest
import redis as redis_lib

HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
PLAN_RUNNER_KEY_PATTERN = "plan-runner:*"
LISTENER_SCRIPT = Path("D:/work/project/tools/monitor-page/scripts/dev-runner-command-listener.py")
PYTHON_EXE = Path("D:/work/project/tools/monitor-page/.venv/Scripts/python.exe")


@pytest.fixture
def real_redis():
    """실제 Redis 연결 — 미실행 시 자동 skip"""
    try:
        r = redis_lib.Redis(decode_responses=True)
        r.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield r
    r.close()


@pytest.fixture
def listener_process(real_redis):
    """Listener 프로세스 lifecycle 관리

    1. 기존 heartbeat 키 삭제 (잔여 상태 초기화)
    2. Listener 프로세스 spawn
    3. heartbeat 키 최대 10초 대기
    4. yield
    5. SIGTERM → 정리
    """
    real_redis.delete(HEARTBEAT_KEY)

    python = str(PYTHON_EXE) if PYTHON_EXE.exists() else "python"
    process = subprocess.Popen(
        [python, str(LISTENER_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # heartbeat 대기 (최대 10초)
    for _ in range(20):
        if real_redis.get(HEARTBEAT_KEY):
            break
        time.sleep(0.5)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("Listener heartbeat not detected within 10 seconds")

    yield process

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def test_plan_file(tmp_path):
    """테스트용 최소 plan 파일 생성"""
    plan = tmp_path / "test-e2e-plan.md"
    plan.write_text(
        "# E2E Test Plan\n\n## TODO\n- [ ] 테스트 항목 1\n",
        encoding="utf-8",
    )
    return plan


@pytest.fixture
def e2e_redis_cleanup(real_redis):
    """plan-runner:* 키 패턴 cleanup (before + after)"""
    # before cleanup
    for key in real_redis.scan_iter("plan-runner:*"):
        real_redis.delete(key)

    yield

    # after cleanup
    for key in real_redis.scan_iter("plan-runner:*"):
        real_redis.delete(key)
