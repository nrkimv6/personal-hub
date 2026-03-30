"""dev_runner E2E 테스트 공유 fixture

실제 Redis + Listener 프로세스를 사용하는 통합/E2E 테스트용 fixture.
fakeredis 기반 단위 테스트와 분리하여 관리.

사용:
    from tests.dev_runner.conftest_e2e import real_redis, listener_process, test_plan_file
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import redis as redis_lib

REDIS_TEST_DB = 15
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
PLAN_RUNNER_KEY_PATTERN = "plan-runner:*"
LISTENER_SCRIPT = Path("D:/work/project/tools/monitor-page/scripts/dev-runner-command-listener.py")
PYTHON_EXE = Path("D:/work/project/tools/monitor-page/.venv/Scripts/python.exe")
PROJECT_ROOT = Path("D:/work/project/tools/monitor-page")
WORKTREE_BASE = PROJECT_ROOT / ".worktrees"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_PLAN_STEMS = ["test_minimal_plan", "test_plan_e2e_mock"]
TEST_PLAN_FILE = "tests/dev_runner/fixtures/test_minimal_plan.md"
TEST_PLAN_FILE_A = "tests/dev_runner/fixtures/test_minimal_plan_a.md"
TEST_PLAN_FILE_B = "tests/dev_runner/fixtures/test_minimal_plan_b.md"
RUNNER_KEY_PREFIX = "plan-runner:runners"


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


@pytest.fixture(scope="class")
def isolated_redis():
    """테스트 전용 Redis db=15 — 격리된 DB 사용으로 운영 DB 오염 방지

    scope="class": http_client(scope="class")와 scope 일치 필요.
    listener_process가 isolated_redis에 의존하므로 scope 통일.
    API(executor_service)가 이 DB를 사용하도록 환경변수 주입 + reconnect.
    """
    from app.modules.dev_runner.services.executor_service import executor_service
    old_db = os.environ.get("PLAN_RUNNER_REDIS_DB")
    os.environ["PLAN_RUNNER_REDIS_DB"] = str(REDIS_TEST_DB)
    executor_service.reconnect()

    try:
        r = redis_lib.Redis(host="localhost", port=6379, db=REDIS_TEST_DB, decode_responses=True)
        r.ping()
    except Exception:
        pytest.skip("Redis not available")
    r.flushdb()
    yield r
    r.flushdb()
    r.close()

    if old_db is not None:
        os.environ["PLAN_RUNNER_REDIS_DB"] = old_db
    else:
        os.environ.pop("PLAN_RUNNER_REDIS_DB", None)
    executor_service.reconnect()


@pytest.fixture(scope="class")
def listener_process(isolated_redis):
    """Listener 프로세스 lifecycle 관리

    scope="class": isolated_redis(scope="class")와 scope 일치.
    클래스 내 모든 테스트가 하나의 Listener 프로세스를 공유 — 재기동 비용 절감.

    1. 기존 heartbeat 키 삭제 (잔여 상태 초기화)
    2. Listener 프로세스 spawn (db=REDIS_TEST_DB 격리)
    3. heartbeat 키 최대 10초 대기 (db=15에서 확인)
    4. yield
    5. SIGTERM → 정리
    """
    isolated_redis.delete(HEARTBEAT_KEY)

    python = str(PYTHON_EXE) if PYTHON_EXE.exists() else "python"
    process = subprocess.Popen(
        [python, str(LISTENER_SCRIPT), "--redis-db", str(REDIS_TEST_DB)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # heartbeat 대기 (최대 10초) — db=15에서 확인
    for _ in range(20):
        if isolated_redis.get(HEARTBEAT_KEY):
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
    # Windows: 프로세스 트리 전체 kill (자식 프로세스 포함)
    import sys as _sys
    if _sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )


@pytest.fixture
def test_plan_file(tmp_path):
    """테스트용 최소 plan 파일 생성"""
    plan = tmp_path / "test-e2e-plan.md"
    plan.write_text(
        "# E2E Test Plan\n\n## TODO\n- [ ] 테스트 항목 1\n",
        encoding="utf-8",
    )
    return plan


def _cleanup_test_worktrees() -> None:
    """테스트 고정 plan 파일의 worktree/branch 잔여물 제거 (멱등)"""
    for stem in TEST_PLAN_STEMS:
        res1 = subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE_BASE / stem), "--force"],
            capture_output=True, cwd=str(PROJECT_ROOT),
        )
        if res1.returncode != 0 and b"not a worktree" not in res1.stderr:
            print(f"[cleanup] git worktree remove failed for {stem}: {res1.stderr.decode('utf-8', errors='ignore').strip()}")

        res2 = subprocess.run(
            ["git", "branch", "-D", f"plan/{stem}"],
            capture_output=True, cwd=str(PROJECT_ROOT),
        )
        if res2.returncode != 0 and b"not found" not in res2.stderr:
            print(f"[cleanup] git branch remove failed for {stem}: {res2.stderr.decode('utf-8', errors='ignore').strip()}")


_PRESERVE_KEYS = {
    "plan-runner:listener:heartbeat",  # Listener 활성 상태 유지
}


def _snapshot_worktrees() -> dict[str, str]:
    """git worktree list --porcelain 파싱 → {path: branch} 딕셔너리 반환"""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
    )
    snapshot: dict[str, str] = {}
    current_path = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[9:]
        elif line.startswith("branch ") and current_path is not None:
            branch = line[7:].replace("refs/heads/", "")
            snapshot[current_path] = branch
            current_path = None
    return snapshot


@pytest.fixture
def e2e_worktree_cleanup():
    """테스트 실행 중 생성된 신규 워크트리를 yield 후 자동 정리

    before snapshot → yield → after snapshot → diff → 신규 항목 제거
    """
    before = _snapshot_worktrees()
    yield
    after = _snapshot_worktrees()
    new_paths = set(after.keys()) - set(before.keys())
    for path in new_paths:
        branch = after[path]
        subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            capture_output=True, cwd=str(PROJECT_ROOT), timeout=10,
        )
        if branch:
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, cwd=str(PROJECT_ROOT), timeout=10,
            )


@pytest.fixture(scope="class")
def e2e_redis_cleanup(isolated_redis):
    """plan-runner:* 키 패턴 cleanup (before + after)

    scope="class": isolated_redis(scope="class")와 scope 일치.
    isolated_redis(db=15)를 사용하여 운영 DB 오염 방지.
    heartbeat 키는 삭제하지 않음 — Listener 프로세스가 활성 중임을 API가 확인해야 함.
    """
    def _cleanup():
        keys_to_del = [key for key in isolated_redis.scan_iter("plan-runner:*") if key not in _PRESERVE_KEYS]
        for key in keys_to_del:
            isolated_redis.delete(key)
        # active_runners set도 명시적으로 비움 (키 삭제만으로는 set 항목이 남을 수 있음)
        try:
            members = isolated_redis.smembers("plan-runner:active_runners") or set()
            for member in members:
                isolated_redis.srem("plan-runner:active_runners", member)
        except Exception:
            pass

    # setup: 이전 잔여물 제거
    _cleanup_test_worktrees()
    _cleanup()
    yield
    # teardown: 테스트 생성 아티팩트 제거
    _cleanup_test_worktrees()
    _cleanup()
