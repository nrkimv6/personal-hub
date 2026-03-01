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
from typing import Set

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


_PRESERVE_KEYS = {
    "plan-runner:listener:heartbeat",  # Listener 활성 상태 유지
}

_PROJECT_ROOT = Path("D:/work/project/tools/monitor-page")


def _snapshot_worktrees() -> Set[str]:
    """현재 git worktree 경로 집합을 캡처하여 반환.

    `git worktree list --porcelain` 출력을 파싱하여 worktree 경로(첫 번째 필드) 집합 반환.
    git 명령 실패 시 빈 집합 반환.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        paths: Set[str] = set()
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                paths.add(line[len("worktree "):].strip())
        return paths
    except Exception:
        return set()


def _get_worktree_branch(path: str) -> str | None:
    """특정 worktree 경로의 브랜치명을 반환.

    `git worktree list --porcelain` 파싱 후 해당 경로 블록에서 branch 추출.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        current_path = None
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                current_path = line[len("worktree "):].strip()
            elif line.startswith("branch ") and current_path == path:
                # "branch refs/heads/plan/xxx" → "plan/xxx"
                ref = line[len("branch "):].strip()
                if ref.startswith("refs/heads/"):
                    return ref[len("refs/heads/"):]
                return ref
        return None
    except Exception:
        return None


@pytest.fixture
def e2e_worktree_cleanup():
    """테스트 전후 워크트리 상태를 비교하여 신규 생성된 워크트리를 자동 정리.

    1. yield 전: `git worktree list --porcelain`으로 기존 worktree 경로 집합 스냅샷
    2. yield 후: 재조회 → diff 계산 → 신규 경로에 대해 `git worktree remove --force` 실행
    3. 신규 워크트리의 브랜치도 `git branch -D`로 삭제
    """
    before = _snapshot_worktrees()
    yield
    after = _snapshot_worktrees()
    new_worktrees = after - before
    for path in new_worktrees:
        branch = _get_worktree_branch(path)
        # worktree 제거
        subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            capture_output=True,
            cwd=str(_PROJECT_ROOT),
            timeout=10,
        )
        # 브랜치 삭제
        if branch:
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True,
                cwd=str(_PROJECT_ROOT),
                timeout=10,
            )


@pytest.fixture
def e2e_redis_cleanup(real_redis):
    """plan-runner:* 키 패턴 cleanup (before + after)

    heartbeat 키는 삭제하지 않음 — Listener 프로세스가 활성 중임을 API가 확인해야 함.
    """
    def _cleanup():
        for key in real_redis.scan_iter("plan-runner:*"):
            if key not in _PRESERVE_KEYS:
                real_redis.delete(key)

    _cleanup()
    yield
    _cleanup()
