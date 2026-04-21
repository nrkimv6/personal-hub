"""dev_runner 테스트 공통 conftest - config 격리로 hang 방지"""

import fnmatch
import json
import os
import subprocess
import sys
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import app.modules.dev_runner.services.worktree_service as worktree_service

# plan_runner.core.stages를 테스트 파일 수집 전에 미리 로드한다.
# test_merge_lock_ownership.py / test_merge_retry_e2e.py 등이 모듈 수준에서
# sys.modules.setdefault("plan_runner.core.stages", <빈 mock>) 를 호출한다.
# conftest는 테스트 파일보다 먼저 import되므로, 여기서 실제 모듈을 로드해두면
# setdefault 호출이 no-op이 되어 StageResult 누락 ImportError를 방지할 수 있다.
try:
    import plan_runner.core.stages  # noqa: F401
except ImportError:
    pass


_SESSION_TEST_BRANCH_PATTERNS = ("runner/t-*", "runner/t5*", "plan/test_*", "plan/t-test*")


def _collect_python_memory_snapshot(cmdline_filter: str | None = None, limit: int = 30) -> dict:
    """python 프로세스 PID/memory 스냅샷 수집."""
    import psutil

    procs = []
    total_mb = 0.0
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "python" not in name:
                continue
            cmdline_list = proc.info.get("cmdline") or []
            cmdline = " ".join(cmdline_list)
            normalized = cmdline.replace("\\", "/")
            if cmdline_filter and cmdline_filter not in normalized:
                continue
            rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
            memory_mb = round(rss / (1024 * 1024), 1)
            total_mb += memory_mb
            procs.append(
                {
                    "pid": int(proc.info["pid"]),
                    "name": proc.info.get("name") or "",
                    "memory_mb": memory_mb,
                    "cmdline": cmdline[:240],
                }
            )
        except Exception:
            continue

    procs.sort(key=lambda item: item["memory_mb"], reverse=True)
    return {
        "captured_at": datetime.now().isoformat(),
        "count": len(procs),
        "total_memory_mb": round(total_mb, 1),
        "processes": procs[:limit],
    }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def merge_retry_memory_snapshot(request):
    """test_merge_retry_e2e 전후 스냅샷 수집. 실패 케이스만 파일 보존."""
    nodeid = request.node.nodeid.replace("\\", "/")
    if "tests/dev_runner/test_merge_retry_e2e.py" not in nodeid:
        yield
        return

    started_at = datetime.now()
    before = _collect_python_memory_snapshot("test_merge_retry_e2e.py")
    yield
    after = _collect_python_memory_snapshot("test_merge_retry_e2e.py")

    failed = any(
        bool(getattr(request.node, f"rep_{phase}", None))
        and not getattr(request.node, f"rep_{phase}").passed
        for phase in ("setup", "call", "teardown")
    )

    snapshot = {
        "nodeid": request.node.nodeid,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now().isoformat(),
        "duration_sec": round((datetime.now() - started_at).total_seconds(), 3),
        "failed": failed,
        "before": before,
        "after": after,
    }

    log_dir = Path("logs") / "pytest_memory_snapshots"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = request.node.nodeid.replace("\\", "_").replace("/", "_").replace("::", "__")
    log_path = log_dir / f"{safe_name}.json"
    log_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    if failed:
        print(f"[memory_snapshot] failed case snapshot: {log_path}")
    else:
        try:
            log_path.unlink()
        except OSError:
            pass


@pytest.fixture(autouse=True)
def restore_listener_noise_filter():
    """listener_noise_filter 모듈을 테스트 전후로 격리.

    8개 테스트 파일이 sys.modules["listener_noise_filter"]를 mock으로 교체하고
    cleanup하지 않아 test_noise_filter_76.py의 is_noise_line이 mock을 import하게 됨.
    각 테스트 전 원본 모듈 상태를 스냅샷하고 테스트 후 복원한다.
    """
    original = sys.modules.get("listener_noise_filter")
    yield
    if original is None:
        sys.modules.pop("listener_noise_filter", None)
    else:
        sys.modules["listener_noise_filter"] = original


def _try_connect_redis():
    """Redis 연결 시도. 실패 시 None 반환."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _should_skip_pid_kill(pid: int) -> bool:
    """pytest 자기 PID는 정리 루틴에서 kill 금지."""
    import os as _os
    try:
        return int(pid) == _os.getpid()
    except Exception:
        return False


def _cleanup_session_test_worktrees() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    worktree_result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=15,
    )

    current_path: str | None = None
    current_branch: str | None = None
    branches_to_delete: set[str] = set()
    for line in worktree_result.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            current_path = line[9:]
            current_branch = None
            continue
        if line.startswith("branch "):
            current_branch = line[7:].replace("refs/heads/", "")
            continue
        if line == "" and current_path:
            if current_branch and any(fnmatch.fnmatch(current_branch, pattern) for pattern in _SESSION_TEST_BRANCH_PATTERNS):
                branches_to_delete.add(current_branch)
                subprocess.run(
                    ["git", "worktree", "remove", "--force", current_path],
                    capture_output=True,
                    cwd=str(repo_root),
                    timeout=15,
                )
            current_path = None
            current_branch = None

    refs_result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/runner", "refs/heads/plan"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=15,
    )
    for branch in {line.strip() for line in refs_result.stdout.splitlines() if line.strip()} | branches_to_delete:
        if not any(fnmatch.fnmatch(branch, pattern) for pattern in _SESSION_TEST_BRANCH_PATTERNS):
            continue
        subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True,
            cwd=str(repo_root),
            timeout=15,
        )


def pytest_sessionfinish(session, exitstatus):
    """pytest 세션 종료 시 test worktree/branch 잔여물을 정리한다."""
    if os.environ.get("PLAN_RUNNER_DISABLE_SESSION_CLEANUP") == "1":
        return

    try:
        _cleanup_session_test_worktrees()
    except Exception as exc:
        sys.stderr.write(f"[session_cleanup] warning: {exc}\n")
        sys.stderr.flush()


@pytest.fixture(autouse=True)
def clear_worktree_cache():
    worktree_service.invalidate_worktree_cache()
    yield
    worktree_service.invalidate_worktree_cache()



@pytest.fixture(autouse=True, scope="session")
def runner_cleanup_report():
    """세션 종료 시 잔류 러너 정리 + 리포트 출력.

    - 세션 시작 전 active_runners + recent_runners 스냅샷 저장
    - 세션 종료 후 신규 잔류 러너 목록 출력 및 삭제
    - test_source가 없는 러너 = (unknown) 표시 → 미수정 TC 식별 단서
    """
    import os as _os, signal as _signal, time as _time, sys as _sys, subprocess as _subprocess

    r = _try_connect_redis()
    if r is None:
        yield
        return

    before_active = r.smembers("plan-runner:active_runners") or set()
    before_recent = set(r.zrange("plan-runner:recent_runners", 0, -1) or [])
    yield

    try:
        after_active = r.smembers("plan-runner:active_runners") or set()
        after_recent = set(r.zrange("plan-runner:recent_runners", 0, -1) or [])
        remaining_active = after_active - before_active
        remaining_recent = after_recent - before_recent
        remaining = remaining_active | remaining_recent

        sep = "=" * 43
        if not remaining:
            sys.stderr.write(f"\n{sep}\n[CLEAN] 잔류 러너 0건\n{sep}\n")
        else:
            lines = [f"\n{sep}", f"[DIRTY] 잔류 러너 {len(remaining)}건 — 자동 정리 시작:"]
            for rid in sorted(remaining):
                plan_file = r.get(f"plan-runner:runners:{rid}:plan_file") or "(none)"
                engine    = r.get(f"plan-runner:runners:{rid}:engine")    or "(none)"
                pid       = r.get(f"plan-runner:runners:{rid}:pid")       or "(none)"
                source    = r.get(f"plan-runner:runners:{rid}:test_source") or "(unknown)"
                lines.append(f"  - {rid:<22} | plan: {plan_file:<30} | engine: {engine:<8} | pid: {pid:<8} | source: {source}")

                # PID kill
                if pid and pid != "(none)":
                    try:
                        _pid_i = int(pid)
                        if _should_skip_pid_kill(_pid_i):
                            lines.append(f"    -> skip self pid kill: {_pid_i}")
                            continue
                        _os.kill(_pid_i, _signal.SIGTERM)
                        _time.sleep(0.5)
                        if _sys.platform == "win32":
                            _subprocess.run(["taskkill", "/F", "/T", "/PID", str(_pid_i)], capture_output=True)
                        else:
                            _os.kill(_pid_i, _signal.SIGKILL)
                    except (ProcessLookupError, ValueError, OSError):
                        pass

                # Redis 키 전체 삭제
                r.srem("plan-runner:active_runners", rid)
                r.zrem("plan-runner:recent_runners", rid)
                keys = r.keys(f"plan-runner:runners:{rid}:*")
                if keys:
                    r.delete(*keys)

            lines.append(f"[DONE] {len(remaining)}건 정리 완료")
            lines.append(sep)
            sys.stderr.write("\n".join(lines) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def redis_cleanup():
    """테스트 전후 실제 Redis에 남은 plan-runner:* 키를 자동 정리.

    - 테스트 시작 전 active_runners 스냅샷을 기록
    - 테스트 종료 후 새로 추가된 runner_id와 관련 키를 삭제
    """
    import os as _os, signal as _signal, time as _time, sys as _sys, subprocess as _subprocess

    r = _try_connect_redis()
    if r is None:
        yield
        return

    before_active = r.smembers("plan-runner:active_runners") or set()
    before_recent = set(r.zrange("plan-runner:recent_runners", 0, -1) or [])

    yield

    try:
        after_active = r.smembers("plan-runner:active_runners") or set()
        after_recent = set(r.zrange("plan-runner:recent_runners", 0, -1) or [])
        new_ids = (after_active - before_active) | (after_recent - before_recent)
        for runner_id in new_ids:
            test_source = r.get(f"plan-runner:runners:{runner_id}:test_source") or "(unknown)"
            # PID kill (프로세스 잔류 방지)
            # http TestClient 기반 테스트는 실제 서브프로세스가 없어 PID가 기록되지 않음.
            # PID 즉시 확인 후 없으면 1회 짧은 대기 — E2E(실제 프로세스)만 장기 대기 필요.
            pid_str = r.get(f"plan-runner:runners:{runner_id}:pid")
            if not pid_str:
                # 1회 단기 대기 후 재확인 (빠른 프로세스가 PID를 늦게 기록하는 경우 대비)
                _time.sleep(0.2)
                pid_str = r.get(f"plan-runner:runners:{runner_id}:pid")
            if pid_str:
                try:
                    _pid_i = int(pid_str)
                    if _should_skip_pid_kill(_pid_i):
                        print(f"[redis_cleanup] skip self pid kill: {runner_id} pid={_pid_i}")
                        _pid_i = None
                    if _pid_i is not None:
                        _os.kill(_pid_i, _signal.SIGTERM)
                    _time.sleep(2)
                    # 강제종료 fallback — /T 플래그로 프로세스 트리 전체 kill
                    if _pid_i is not None:
                        if _sys.platform == "win32":
                            _subprocess.run(["taskkill", "/F", "/T", "/PID", str(_pid_i)], capture_output=True)
                        else:
                            _os.kill(_pid_i, _signal.SIGKILL)
                except (ProcessLookupError, ValueError, OSError):
                    pass
            print(f"[redis_cleanup] 정리: {runner_id} (source: {test_source})")
            r.srem("plan-runner:active_runners", runner_id)
            r.zrem("plan-runner:recent_runners", runner_id)
            keys = r.keys(f"plan-runner:runners:{runner_id}:*")
            if keys:
                r.delete(*keys)
            # race condition 대응: PID kill 후 listener가 recent_runners에 재등록할 수 있음
            # 실제 PID가 있었던 경우(실제 프로세스)만 2초 대기 후 재확인 — TestClient 테스트는 스킵
            if pid_str:
                _time.sleep(2)
                r.srem("plan-runner:active_runners", runner_id)
                r.zrem("plan-runner:recent_runners", runner_id)
                stale_keys = r.keys(f"plan-runner:runners:{runner_id}:*")
                if stale_keys:
                    r.delete(*stale_keys)

        # merge-queue:* 키 정리
        for key in r.scan_iter("plan-runner:merge-queue:*"):
            r.delete(key)
        # merge-turn:* 키 정리
        for key in r.scan_iter("plan-runner:merge-turn:*"):
            r.delete(key)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def dev_runner_config_isolation(tmp_path):
    """모든 dev_runner 테스트에서 config를 tmp 경로로 격리.

    모듈-레벨 싱글톤(plan_service, db_service 등)이 import 시
    실제 파일시스템에 접근하는 것을 방지합니다.
    """
    reg_file = tmp_path / "registered_paths.json"
    ign_file = tmp_path / "ignored_plans.json"
    reg_file.write_text("[]", encoding="utf-8")
    ign_file.write_text("[]", encoding="utf-8")

    mock_config = MagicMock()
    mock_config.REGISTERED_PATHS_FILE = reg_file
    mock_config.EXTERNAL_PLANS_FILE = tmp_path / "external_plans.json"
    mock_config.IGNORED_PLANS_FILE = ign_file
    mock_config.WTOOLS_BASE_DIR = tmp_path / "wtools"
    mock_config.PLAN_DIR = Path("common/docs/plan")
    mock_config.PROJECT_DIRS = []
    mock_config.ALLOWED_PATHS = [str(tmp_path)]
    mock_config.LOG_DIR = Path("common/logs")
    mock_config.LOG_FILE_PATTERN = "plan-runner-*.log"

    with patch("app.modules.dev_runner.services.plan_service.config", mock_config):
        yield mock_config


@pytest.fixture
def isolated_redis():
    """격리된 Redis 목업 클라이언트.

    plan-runner:* 패턴 키를 in-memory dict로 관리합니다.
    isolated_redis를 사용하는 테스트에 한해 runner cleanup이 자동 적용됩니다.
    """
    storage: dict = {}

    mock = MagicMock()

    def _set(key, value, *args, **kwargs):
        storage[key] = value

    def _get(key):
        return storage.get(key)

    def _delete(*keys):
        for key in keys:
            storage.pop(key, None)

    def _mget(keys):
        return [storage.get(k) for k in keys]

    def _smembers(key):
        val = storage.get(key, set())
        return val if isinstance(val, set) else set()

    def _sadd(key, *values):
        if key not in storage:
            storage[key] = set()
        if isinstance(storage[key], set):
            storage[key].update(values)

    def _srem(key, *values):
        if isinstance(storage.get(key), set):
            storage[key].discard(*values)

    def _keys(pattern):
        import fnmatch
        return [k for k in storage if fnmatch.fnmatch(k, pattern)]

    mock.set.side_effect = _set
    mock.get.side_effect = _get
    mock.delete.side_effect = _delete
    mock.mget.side_effect = _mget
    mock.smembers.side_effect = _smembers
    mock.sadd.side_effect = _sadd
    mock.srem.side_effect = _srem
    mock.keys.side_effect = _keys

    yield mock

    # teardown: plan-runner:* 패턴 키 자동 정리
    stale_keys = [k for k in list(storage.keys()) if k.startswith("plan-runner:")]
    for key in stale_keys:
        storage.pop(key, None)


def attach_default_redis_behaviors(redis_mock: MagicMock) -> MagicMock:
    """Redis MagicMock 기본 동작을 엄격 모드로 고정한다.

    기본 반환값이 다시 MagicMock으로 누출되어 분기 조건을 오염시키지 않도록
    핵심 메서드의 기본 반환값을 명시적으로 지정한다.
    """
    redis_mock.get.side_effect = lambda *_args, **_kwargs: None
    redis_mock.set.return_value = True
    redis_mock.delete.return_value = 0
    redis_mock.expire.return_value = True
    redis_mock.persist.return_value = True
    redis_mock.srem.return_value = 0
    redis_mock.zadd.return_value = 1
    redis_mock.lrem.return_value = 0
    redis_mock.publish.return_value = 1
    redis_mock.ping.return_value = True
    redis_mock.smembers.return_value = set()
    redis_mock.zrange.return_value = []
    redis_mock.keys.return_value = []
    redis_mock.scan_iter.return_value = iter(())
    return redis_mock


def assert_no_magicmock_leak(value, method_name: str = "redis.get") -> None:
    """strict mock 경계에서 MagicMock 기본값 누출 여부를 검사한다."""
    assert not isinstance(value, MagicMock), (
        f"{method_name} returned MagicMock leak. "
        "Use attach_default_redis_behaviors()/strict_redis_mock for explicit defaults."
    )


def make_strict_redis_mock() -> MagicMock:
    """Redis MagicMock factory with explicit defaults and leak guard."""
    redis_mock = attach_default_redis_behaviors(MagicMock())
    assert_no_magicmock_leak(
        redis_mock.get("plan-runner:runners:strict-check:merge_requested"),
        "redis.get",
    )
    return redis_mock


@pytest.fixture
def strict_redis_mock() -> MagicMock:
    """기본 반환값 누출을 방지한 strict Redis MagicMock."""
    return make_strict_redis_mock()
