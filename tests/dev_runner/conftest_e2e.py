"""dev_runner E2E 테스트 공유 fixture

실제 Redis + Listener 프로세스를 사용하는 통합/E2E 테스트용 fixture.
fakeredis 기반 단위 테스트와 분리하여 관리.

사용:
    from tests.dev_runner.conftest_e2e import real_redis, listener_process, test_plan_file
"""
import json
import os
import fnmatch
import re
import subprocess
import time
from pathlib import Path

import pytest
import redis as redis_lib

from tests.dev_runner._path_helpers import (
    get_listener_script_path,
    get_project_python,
    get_repo_root,
)

REDIS_TEST_DB = 15
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"
PLAN_RUNNER_KEY_PATTERN = "plan-runner:*"
LISTENER_SCRIPT = get_listener_script_path()
PYTHON_EXE = Path(get_project_python())
PROJECT_ROOT = get_repo_root()
WORKTREE_BASE = PROJECT_ROOT / ".worktrees"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_PLAN_STEMS = [
    "test_minimal_plan",
    "test_minimal_plan_a",
    "test_minimal_plan_b",
    "test_plan_e2e_mock",
]
TEST_PLAN_FILE = "tests/dev_runner/fixtures/test_minimal_plan.md"
TEST_PLAN_FILE_A = "tests/dev_runner/fixtures/test_minimal_plan_a.md"
TEST_PLAN_FILE_B = "tests/dev_runner/fixtures/test_minimal_plan_b.md"
RUNNER_KEY_PREFIX = "plan-runner:runners"
TEST_BRANCH_PATTERNS = ("runner/t-*", "runner/t5*", "plan/test_*", "plan/t-test*")


@pytest.fixture
def codex_runtime_failure_stderr():
    """codex runtime 실패 재현용 synthetic stderr 라인."""
    return [
        "Error: unknown variant `xhigh`, expected one of `minimal`, `low`, `medium`, `high`",
        "in `model_reasoning_effort`",
    ]


@pytest.fixture
def real_redis():
    """실제 Redis 연결 — 미실행 시 자동 skip"""
    try:
        r = redis_lib.Redis(decode_responses=True)
        r.ping()
    except Exception:
        pytest.fail("Redis not available — 테스트 환경 미충족")
    yield r
    r.close()


@pytest.fixture(scope="class")
def isolated_redis_db15():
    """테스트 전용 Redis db=15 — 격리된 DB 사용으로 운영 DB 오염 방지

    scope="class": http_client(scope="class")와 scope 일치 필요.
    listener_process가 isolated_redis_db15에 의존하므로 scope 통일.
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
        pytest.fail("Redis not available — 테스트 환경 미충족")
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
def listener_process(isolated_redis_db15):
    """Listener 프로세스 lifecycle 관리

    scope="class": isolated_redis_db15(scope="class")와 scope 일치.
    클래스 내 모든 테스트가 하나의 Listener 프로세스를 공유 — 재기동 비용 절감.

    1. 기존 heartbeat 키 삭제 (잔여 상태 초기화)
    2. Listener 프로세스 spawn (db=REDIS_TEST_DB 격리)
    3. heartbeat 키 최대 10초 대기 (db=15에서 확인)
    4. yield
    5. SIGTERM → 정리
    """
    isolated_redis_db15.delete(HEARTBEAT_KEY)

    python = str(PYTHON_EXE) if PYTHON_EXE.exists() else "python"
    process = subprocess.Popen(
        [python, str(LISTENER_SCRIPT), "--redis-db", str(REDIS_TEST_DB)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # heartbeat 대기 (최대 10초) — db=15에서 확인
    for _ in range(20):
        if isolated_redis_db15.get(HEARTBEAT_KEY):
            break
        time.sleep(0.5)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
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


def copy_fixture_plan_to_tmp(
    tmp_path: Path,
    fixture_name: str = "test_minimal_plan.md",
) -> Path:
    """Copy a shared fixture plan into a per-test path before runner execution."""
    src = FIXTURES_DIR / fixture_name
    content = src.read_text(encoding="utf-8")
    content = re.sub(r"^> branch:.*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^> worktree:.*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^> worktree-owner:.*\n", "", content, flags=re.MULTILINE)
    plan = tmp_path / fixture_name
    plan.write_text(content, encoding="utf-8")
    return plan


def _cleanup_test_worktrees() -> None:
    """테스트 고정 plan 파일의 worktree/branch 잔여물 제거 (멱등)"""
    worktree_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
    )
    current_path = None
    current_branch = None
    current_prunable = False
    seen_branches: set[str] = set()
    needs_prune = False
    for line in worktree_list.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            current_path = line[9:]
            current_branch = None
            current_prunable = False
            continue
        if line.startswith("branch "):
            current_branch = line[7:].replace("refs/heads/", "")
            continue
        if line.startswith("prunable"):
            current_prunable = True
            continue
        if line == "" and current_path:
            if current_branch and any(fnmatch.fnmatch(current_branch, pattern) for pattern in TEST_BRANCH_PATTERNS):
                seen_branches.add(current_branch)
                res = subprocess.run(
                    ["git", "worktree", "remove", current_path, "--force"],
                    capture_output=True, cwd=str(PROJECT_ROOT), timeout=15,
                )
                if current_prunable or b"not a working tree" in res.stderr or b"not a worktree" in res.stderr:
                    needs_prune = True
                if res.returncode != 0 and b"not a working tree" not in res.stderr and b"not a worktree" not in res.stderr:
                    print(f"[cleanup] git worktree remove failed for {current_branch}: {res.stderr.decode('utf-8', errors='ignore').strip()}")
            current_path = None
            current_branch = None
            current_prunable = False

    if needs_prune:
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True, cwd=str(PROJECT_ROOT), timeout=15,
        )

    branch_list = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/runner", "refs/heads/plan"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
    )
    for branch in {line.strip() for line in branch_list.stdout.splitlines() if line.strip()} | seen_branches:
        if not any(fnmatch.fnmatch(branch, pattern) for pattern in TEST_BRANCH_PATTERNS):
            continue
        res = subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True, cwd=str(PROJECT_ROOT), timeout=15,
        )
        if res.returncode != 0 and b"not found" not in res.stderr:
            print(f"[cleanup] git branch remove failed for {branch}: {res.stderr.decode('utf-8', errors='ignore').strip()}")

    for stem in TEST_PLAN_STEMS:
        res1 = subprocess.run(
            ["git", "worktree", "remove", str(WORKTREE_BASE / stem), "--force"],
            capture_output=True, cwd=str(PROJECT_ROOT),
        )
        if b"not a worktree" in res1.stderr or b"not a working tree" in res1.stderr:
            subprocess.run(
                ["git", "worktree", "prune"],
                capture_output=True, cwd=str(PROJECT_ROOT), timeout=15,
            )
        if res1.returncode != 0 and b"not a worktree" not in res1.stderr and b"not a working tree" not in res1.stderr:
            print(f"[cleanup] git worktree remove failed for {stem}: {res1.stderr.decode('utf-8', errors='ignore').strip()}")

        res2 = subprocess.run(
            ["git", "branch", "-D", f"plan/{stem}"],
            capture_output=True, cwd=str(PROJECT_ROOT),
        )
        if res2.returncode != 0 and b"not found" not in res2.stderr:
            print(f"[cleanup] git branch remove failed for {stem}: {res2.stderr.decode('utf-8', errors='ignore').strip()}")

        # runner/prunable cleanup 뒤에도 반복 호출이 같은 fixture 상태를 유지하도록 header residue를 정리한다.
        fixture_path = FIXTURES_DIR / f"{stem}.md"
        if fixture_path.exists():
            try:
                lines = fixture_path.read_text(encoding="utf-8").splitlines(keepends=True)
                cleaned = [ln for ln in lines if not re.match(r"^>\s*(branch|worktree|worktree-owner):", ln)]
                if cleaned != lines:
                    fixture_path.write_text("".join(cleaned), encoding="utf-8")
            except Exception as e:
                print(f"[cleanup] fixture header cleanup failed for {stem}: {e}")


_PRESERVE_KEYS = {
    "plan-runner:listener:heartbeat",  # Listener 활성 상태 유지
}


def _snapshot_worktrees() -> dict[str, dict[str, object]]:
    """git worktree list --porcelain 파싱 → {path: {branch, prunable}} 딕셔너리 반환"""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
    )
    snapshot: dict[str, dict[str, object]] = {}
    current_path = None
    current_info: dict[str, object] | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[9:]
            current_info = {"branch": None, "prunable": False}
        elif line.startswith("branch ") and current_path is not None:
            branch = line[7:].replace("refs/heads/", "")
            if current_info is not None:
                current_info["branch"] = branch
        elif line.startswith("prunable") and current_path is not None:
            if current_info is not None:
                current_info["prunable"] = True
        elif not line and current_path is not None and current_info is not None:
            snapshot[current_path] = current_info
            current_path = None
            current_info = None
    if current_path is not None and current_info is not None:
        snapshot[current_path] = current_info
    return snapshot


def _snapshot_runner_branches() -> set[str]:
    """refs/heads/runner/* 브랜치명 스냅샷"""
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/runner"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=15,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


@pytest.fixture
def e2e_worktree_cleanup():
    """테스트 실행 중 생성된 신규 워크트리를 yield 후 자동 정리

    before snapshot → yield → after snapshot → diff → 신규 항목 제거
    """
    before = _snapshot_worktrees()
    before_branches = _snapshot_runner_branches()
    yield
    after = _snapshot_worktrees()
    after_branches = _snapshot_runner_branches()
    new_paths = set(after.keys()) - set(before.keys())
    prunable_paths = {
        path
        for path, info in after.items()
        if info.get("prunable") and not before.get(path, {}).get("prunable")
    }
    needs_prune = bool(prunable_paths)
    for path in new_paths | prunable_paths:
        branch = after.get(path, {}).get("branch")
        res = subprocess.run(
            ["git", "worktree", "remove", "--force", path],
            capture_output=True, cwd=str(PROJECT_ROOT), timeout=10,
        )
        if res.returncode != 0 and (b"not a working tree" in res.stderr or b"not a worktree" in res.stderr):
            needs_prune = True
        if branch and branch in (after_branches - before_branches):
            subprocess.run(
                ["git", "branch", "-D", branch],
                capture_output=True, cwd=str(PROJECT_ROOT), timeout=10,
            )
    if needs_prune:
        subprocess.run(
            ["git", "worktree", "prune"],
            capture_output=True, cwd=str(PROJECT_ROOT), timeout=15,
        )


@pytest.fixture(scope="class")
def e2e_redis_cleanup(isolated_redis_db15):
    """plan-runner:* 키 패턴 cleanup (before + after)

    scope="class": isolated_redis_db15(scope="class")와 scope 일치.
    isolated_redis_db15(db=15)를 사용하여 운영 DB 오염 방지.
    heartbeat 키는 삭제하지 않음 — Listener 프로세스가 활성 중임을 API가 확인해야 함.
    """
    def _cleanup():
        keys_to_del = [key for key in isolated_redis_db15.scan_iter("plan-runner:*") if key not in _PRESERVE_KEYS]
        for key in keys_to_del:
            isolated_redis_db15.delete(key)
        # active_runners set도 명시적으로 비움 (키 삭제만으로는 set 항목이 남을 수 있음)
        try:
            members = isolated_redis_db15.smembers("plan-runner:active_runners") or set()
            for member in members:
                isolated_redis_db15.srem("plan-runner:active_runners", member)
        except Exception:
            pass

    # setup: 이전 잔여물 제거
    _cleanup_test_worktrees()
    _cleanup()
    yield
    # teardown: 테스트 생성 아티팩트 제거
    _cleanup_test_worktrees()
    _cleanup()
