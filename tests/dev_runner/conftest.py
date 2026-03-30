"""dev_runner 테스트 공통 conftest - config 격리로 hang 방지"""

import json
import sys
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock


@contextmanager
def mock_merge_queue_turn(repo_id: str):
    """fakeredis 기반 E2E TC에서 merge_queue 함수 mock 헬퍼.

    ⚠️ fakeredis는 Lua eval 미지원 — merge_queue.py의 acquire_merge_turn()이
    _ENQUEUE_LUA 스크립트를 eval()로 실행하므로 `unknown command 'eval'` 오류 발생.
    merge_queue 함수를 직접 호출하는 모든 TC는 반드시 이 context manager를 사용할 것.

    Usage:
        with mock_merge_queue_turn("my-repo"):
            # TC 코드 — acquire/release는 mock으로 대체됨
    """
    with patch("merge_queue.acquire_merge_turn", return_value=True), \
         patch("merge_queue.release_merge_turn", return_value=True), \
         patch("merge_queue._get_repo_id", return_value=repo_id):
        yield


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
                        _os.kill(int(pid), _signal.SIGTERM)
                        _time.sleep(0.5)
                        if _sys.platform == "win32":
                            _subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                        else:
                            _os.kill(int(pid), _signal.SIGKILL)
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
            # PID kill (프로세스 잔류 방지) — PID 기록 지연 대응: 최대 5초 retry
            pid_str = None
            for _ in range(10):  # 최대 5초 대기
                pid_str = r.get(f"plan-runner:runners:{runner_id}:pid")
                if pid_str:
                    break
                _time.sleep(0.5)
            if pid_str:
                try:
                    _os.kill(int(pid_str), _signal.SIGTERM)
                    _time.sleep(2)
                    # 강제종료 fallback — /T 플래그로 프로세스 트리 전체 kill
                    if _sys.platform == "win32":
                        _subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid_str)], capture_output=True)
                    else:
                        _os.kill(int(pid_str), _signal.SIGKILL)
                except (ProcessLookupError, ValueError, OSError):
                    pass
            print(f"[redis_cleanup] 정리: {runner_id} (source: {test_source})")
            r.srem("plan-runner:active_runners", runner_id)
            r.zrem("plan-runner:recent_runners", runner_id)
            keys = r.keys(f"plan-runner:runners:{runner_id}:*")
            if keys:
                r.delete(*keys)
            # race condition 대응: PID kill 후 listener가 recent_runners에 재등록할 수 있음
            # 2초 대기 후 재확인 + 재삭제
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
