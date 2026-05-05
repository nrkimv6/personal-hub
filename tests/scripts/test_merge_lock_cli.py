"""
merge_lock_cli.py 단위/통합 TC (fakeredis 기반)

RIGHT-BICEP:
  R — acquire/release 정상 흐름
  B — 경계 조건 (큐 없는 runner release, 빈 큐 acquire)
  E — 예외/오류 (redis 미연결, timeout)

T3 동시성 통합 TC:
  - 수동 세션 두 개 동시 acquire 직렬화 검증
  - auto(uuid) + manual runner 큐 공유 검증
  - stale holder 사망 시 다음 runner 자동 승격 검증

주의: fakeredis 2.x는 lupa 없이 Lua eval을 지원하지 않는다.
      merge_queue의 _ENQUEUE_LUA 의존 부분은 patch로 우회하거나
      pure-Python enqueue 함수로 대체한다.
"""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 프로젝트 루트 경로 (tests/scripts → 프로젝트 루트)
_PROJ_ROOT = Path(__file__).resolve().parents[2]
_PLAN_RUNNER_DIR = _PROJ_ROOT / "scripts" / "plan_runner"
_CLI_PATH = _PLAN_RUNNER_DIR / "merge_lock_cli.py"

# fakeredis 임포트 — 없으면 테스트 전체 스킵
try:
    import fakeredis

    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not FAKEREDIS_AVAILABLE, reason="fakeredis 미설치"
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis():
    """fakeredis 인스턴스 — 각 테스트마다 독립 인스턴스를 반환한다."""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server)
    yield client
    client.close()


@pytest.fixture()
def plan_runner_sys_path():
    """merge_queue / merge_lock_cli import를 위한 sys.path 패치."""
    original = sys.path[:]
    if str(_PLAN_RUNNER_DIR) not in sys.path:
        sys.path.insert(0, str(_PLAN_RUNNER_DIR))
    yield
    sys.path[:] = original


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────


def _import_cli(plan_runner_sys_path):
    """merge_lock_cli 모듈을 동적으로 임포트한다."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("merge_lock_cli", _CLI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_queue(plan_runner_sys_path):
    """merge_queue 모듈을 동적으로 임포트한다."""
    import importlib.util

    queue_path = _PLAN_RUNNER_DIR / "merge_queue.py"
    spec = importlib.util.spec_from_file_location("merge_queue", queue_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _enqueue_pure(redis_client, queue_key: str, runner_id: str, queue_ttl: int = 1200):
    """Lua eval 없이 순수 Python으로 중복 방지 enqueue를 구현한다.

    merge_queue._ENQUEUE_LUA 동등 로직: 이미 있으면 skip, 없으면 RPUSH.
    테스트에서 fakeredis의 eval 미지원을 우회하기 위해 사용한다.
    """
    items = redis_client.lrange(queue_key, 0, -1)
    runner_bytes = runner_id.encode() if isinstance(runner_id, str) else runner_id
    for item in items:
        if (item.decode() if isinstance(item, bytes) else item) == runner_id:
            return 0  # 이미 있음
    redis_client.rpush(queue_key, runner_id)
    redis_client.expire(queue_key, queue_ttl)
    return 1


def _acquire_with_pure_enqueue(queue_mod, redis_client, runner_id: str, repo_id: str, timeout: int = 10) -> bool:
    """_ENQUEUE_LUA를 pure-Python enqueue로 패치한 acquire_merge_turn 실행."""
    queue_key = queue_mod.get_queue_key(repo_id)

    # _ENQUEUE_LUA eval 호출을 pure-Python으로 대체
    def patched_eval(script, numkeys, *args):
        if numkeys == 1:
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(redis_client, key, val)
        return 0

    with patch.object(redis_client, "eval", side_effect=patched_eval):
        return queue_mod.acquire_merge_turn(
            redis_client, runner_id=runner_id, repo_id=repo_id, timeout=timeout
        )


# ── Phase T1: 단위 TC (RIGHT / BOUNDARY / ERROR) ─────────────────────────────


class TestTimeoutResolution:
    """R/B: CLI timeout resolution contract."""

    def test_resolve_timeout_right_default_uses_24h(self, plan_runner_sys_path, monkeypatch):
        cli = _import_cli(plan_runner_sys_path)

        monkeypatch.delenv("MERGE_TEST_LOCK_TIMEOUT", raising=False)

        assert cli._resolve_timeout(None) == 86400

    def test_resolve_timeout_order_env_overrides_cli(self, plan_runner_sys_path, monkeypatch):
        cli = _import_cli(plan_runner_sys_path)

        monkeypatch.setenv("MERGE_TEST_LOCK_TIMEOUT", "42")

        assert cli._resolve_timeout(600) == 42

    def test_resolve_timeout_boundary_cli_overrides_default(self, plan_runner_sys_path, monkeypatch):
        cli = _import_cli(plan_runner_sys_path)

        monkeypatch.delenv("MERGE_TEST_LOCK_TIMEOUT", raising=False)

        assert cli._resolve_timeout(123) == 123


class TestAcquireRight:
    """R(정상): 빈 큐에서 acquire → 즉시 획득."""

    def test_acquire_R_immediate_when_queue_empty(
        self, fake_redis, plan_runner_sys_path
    ):
        cli = _import_cli(plan_runner_sys_path)
        queue_mod = _import_queue(plan_runner_sys_path)

        runner_id = "manual-20260425120000-9999-test-slug"
        timeout = 10
        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        def patched_eval(script, numkeys, *args):
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(fake_redis, key, val)

        captured_stdout = []

        import builtins
        original_print = builtins.print

        def mock_print(*args, **kwargs):
            if kwargs.get("file") is None:
                captured_stdout.append(" ".join(str(a) for a in args))

        with patch.object(cli, "_get_redis_client", return_value=fake_redis), \
             patch.object(fake_redis, "eval", side_effect=patched_eval), \
             patch("builtins.print", side_effect=mock_print):
            with pytest.raises(SystemExit) as exc_info:
                cli.cmd_acquire(runner_id, timeout)

        assert exc_info.value.code == 0, f"exit code should be 0, got {exc_info.value.code}"
        assert any(f"ACQUIRED {runner_id}" in s for s in captured_stdout), (
            f"stdout should contain 'ACQUIRED {runner_id}', got: {captured_stdout}"
        )


class TestAcquireError:
    """E(오류): redis 연결 실패 → exit 3 + REDIS_UNAVAILABLE."""

    def test_acquire_E_redis_unavailable_returns_3(self, plan_runner_sys_path):
        cli = _import_cli(plan_runner_sys_path)

        runner_id = "manual-20260425120000-9999-test-slug"

        def raise_exit_3():
            sys.exit(3)

        with patch.object(cli, "_get_redis_client", side_effect=lambda: raise_exit_3()):
            with pytest.raises(SystemExit) as exc_info:
                cli.cmd_acquire(runner_id, timeout=5)

        assert exc_info.value.code == 3


class TestAcquireBoundaryTimeout:
    """B(경계): 다른 runner가 점유 중 + timeout 짧게 → exit 2."""

    def test_acquire_B_timeout_returns_2(
        self, fake_redis, plan_runner_sys_path
    ):
        queue_mod = _import_queue(plan_runner_sys_path)
        cli = _import_cli(plan_runner_sys_path)

        blocker_id = "manual-20260425110000-1111-blocker"
        waiter_id = "manual-20260425120000-2222-waiter"

        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        # blocker를 큐 맨 앞에 enqueue (turn 점유 시뮬레이션)
        fake_redis.rpush(queue_key, blocker_id)
        fake_redis.expire(queue_key, 1200)

        # blocker가 살아있는 것처럼 만들기: PID 키 없이 status=running만 설정
        # (pid_raw가 None이면 status 키를 체크함 → running이면 stale 아님)
        fake_redis.set(f"plan-runner:runners:{blocker_id}:status", "running")

        def patched_eval(script, numkeys, *args):
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(fake_redis, key, val)

        with patch.object(cli, "_get_redis_client", return_value=fake_redis), \
             patch.object(fake_redis, "eval", side_effect=patched_eval):
            with pytest.raises(SystemExit) as exc_info:
                # timeout=1초 → 즉시 timeout (blocker가 살아있고 release 안 함)
                cli.cmd_acquire(waiter_id, timeout=1)

        assert exc_info.value.code == 2, (
            f"timeout 케이스는 exit 2여야 함, got {exc_info.value.code}"
        )


class TestReleaseRight:
    """R(정상): turn 보유 중 release → exit 0 + 큐에서 제거."""

    def test_release_R_when_holding_turn(
        self, fake_redis, plan_runner_sys_path
    ):
        cli = _import_cli(plan_runner_sys_path)
        queue_mod = _import_queue(plan_runner_sys_path)

        runner_id = "manual-20260425120000-9999-test-slug"
        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        # 큐에 enqueue
        fake_redis.rpush(queue_key, runner_id)

        captured_stdout = []

        import builtins
        def mock_print(*args, **kwargs):
            if kwargs.get("file") is None:
                captured_stdout.append(" ".join(str(a) for a in args))

        with patch.object(cli, "_get_redis_client", return_value=fake_redis), \
             patch("builtins.print", side_effect=mock_print):
            with pytest.raises(SystemExit) as exc_info:
                cli.cmd_release(runner_id)

        assert exc_info.value.code == 0
        assert any(f"RELEASED {runner_id}" in s for s in captured_stdout)

        # 큐에서 제거됐는지 검증
        queue_contents = [
            item.decode() if isinstance(item, bytes) else item
            for item in fake_redis.lrange(queue_key, 0, -1)
        ]
        assert runner_id not in queue_contents, (
            f"runner_id should be removed from queue after release, queue={queue_contents}"
        )


class TestReleaseBoundaryNotInQueue:
    """B(경계): 큐에 없는 runner_id로 release → exit 0 (no-op)."""

    def test_release_B_when_not_in_queue_returns_0(
        self, fake_redis, plan_runner_sys_path
    ):
        cli = _import_cli(plan_runner_sys_path)

        runner_id = "manual-20260425120000-9999-nonexistent"

        with patch.object(cli, "_get_redis_client", return_value=fake_redis):
            with pytest.raises(SystemExit) as exc_info:
                cli.cmd_release(runner_id)

        assert exc_info.value.code == 0, (
            f"큐에 없는 runner release는 no-op(exit 0)이어야 함, got {exc_info.value.code}"
        )


# ── Phase T3: 동시성 통합 TC ──────────────────────────────────────────────────


class TestConcurrentManualSessions:
    """T3: 두 manual runner 동시 acquire → 직렬화 검증."""

    def test_concurrent_manual_sessions_serialized(
        self, plan_runner_sys_path
    ):
        """fakeredis 동일 큐에 두 manual runner를 동시에 acquire.

        한쪽이 즉시 acquire, 다른 쪽은 BRPOP 대기 → 첫쪽 release → 두 번째 acquire.
        머지 순서 직렬화 검증.
        """
        server = fakeredis.FakeServer()
        r1 = fakeredis.FakeRedis(server=server)
        r2 = fakeredis.FakeRedis(server=server)

        queue_mod = _import_queue(plan_runner_sys_path)
        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        acquire_order = []
        release_done = threading.Event()

        runner1 = "manual-20260425120000-1111-session1"
        runner2 = "manual-20260425120001-2222-session2"

        def patched_eval(script, numkeys, *args):
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(r1, key, val)

        def acquire_and_record(client, rid, wait_event=None):
            with patch.object(client, "eval", side_effect=patched_eval):
                success = queue_mod.acquire_merge_turn(
                    client, runner_id=rid, repo_id=repo_id, timeout=15
                )
            if success:
                acquire_order.append(rid)
            if wait_event:
                wait_event.wait(timeout=5)
            queue_mod.release_merge_turn(client, runner_id=rid, repo_id=repo_id)

        t1 = threading.Thread(target=acquire_and_record, args=(r1, runner1, release_done))
        t2 = threading.Thread(target=acquire_and_record, args=(r2, runner2))

        t1.start()
        time.sleep(0.15)  # runner1이 먼저 enqueue되도록 대기
        t2.start()
        time.sleep(0.3)   # runner2가 큐에 등록되도록 대기
        release_done.set()  # runner1 보유 해제 신호

        t1.join(timeout=20)
        t2.join(timeout=20)

        assert len(acquire_order) == 2, (
            f"두 runner 모두 acquire 성공해야 함, got {acquire_order}"
        )
        assert acquire_order[0] == runner1, (
            f"runner1이 먼저 acquire해야 함, order={acquire_order}"
        )
        assert acquire_order[1] == runner2, (
            f"runner2가 두 번째 acquire해야 함, order={acquire_order}"
        )


class TestManualVsAutoRunnerShareQueue:
    """T3: auto(uuid) runner + manual runner가 동일 큐에서 turn 양보 검증."""

    def test_manual_vs_auto_runner_share_queue(
        self, plan_runner_sys_path
    ):
        """auto runner_id(uuid 형식)와 manual runner_id가 동일 큐를 공유한다."""
        server = fakeredis.FakeServer()
        r_auto = fakeredis.FakeRedis(server=server)
        r_manual = fakeredis.FakeRedis(server=server)

        queue_mod = _import_queue(plan_runner_sys_path)
        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        auto_runner = "550e8400-e29b-41d4-a716-446655440000"  # UUID 형식
        manual_runner = "manual-20260425130000-3333-my-plan"

        acquire_order = []
        release_done = threading.Event()

        def patched_eval_shared(script, numkeys, *args):
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(r_auto, key, val)

        def run_auto():
            with patch.object(r_auto, "eval", side_effect=patched_eval_shared):
                success = queue_mod.acquire_merge_turn(
                    r_auto, runner_id=auto_runner, repo_id=repo_id, timeout=15
                )
            if success:
                acquire_order.append(auto_runner)
            release_done.wait(timeout=5)
            queue_mod.release_merge_turn(r_auto, runner_id=auto_runner, repo_id=repo_id)

        def run_manual():
            with patch.object(r_manual, "eval", side_effect=patched_eval_shared):
                success = queue_mod.acquire_merge_turn(
                    r_manual, runner_id=manual_runner, repo_id=repo_id, timeout=15
                )
            if success:
                acquire_order.append(manual_runner)
            queue_mod.release_merge_turn(r_manual, runner_id=manual_runner, repo_id=repo_id)

        t_auto = threading.Thread(target=run_auto)
        t_manual = threading.Thread(target=run_manual)

        t_auto.start()
        time.sleep(0.15)
        t_manual.start()
        time.sleep(0.3)
        release_done.set()

        t_auto.join(timeout=20)
        t_manual.join(timeout=20)

        assert len(acquire_order) == 2, (
            f"auto+manual 모두 acquire 성공해야 함, got {acquire_order}"
        )
        assert acquire_order[0] == auto_runner
        assert acquire_order[1] == manual_runner


class TestStaleManualHolderAutoPromoted:
    """T3: manual runner가 lock 점유 후 release 없이 사망 → 다음 runner stale 제거로 승격."""

    def test_stale_manual_holder_auto_promoted(
        self, plan_runner_sys_path
    ):
        """stale manual holder 시뮬레이션.

        _is_pid_alive를 False로 mock → _remove_if_stale이 자동 제거.
        다음 runner가 turn을 획득해야 한다.
        """
        server = fakeredis.FakeServer()
        r_stale = fakeredis.FakeRedis(server=server)
        r_next = fakeredis.FakeRedis(server=server)

        queue_mod = _import_queue(plan_runner_sys_path)
        repo_id = queue_mod._get_repo_id(_PROJ_ROOT)
        queue_key = queue_mod.get_queue_key(repo_id)

        stale_runner = "manual-20260425110000-0000-stale"
        next_runner = "manual-20260425120000-4444-next"

        # stale_runner를 큐 맨 앞에 enqueue (이미 사망한 것처럼)
        r_stale.rpush(queue_key, stale_runner)
        r_stale.expire(queue_key, 1200)

        # stale_runner의 PID 키를 redis에 등록 (pid=999999 → 사망 시뮬레이션)
        r_stale.set(f"plan-runner:runners:{stale_runner}:pid", "999999")

        def patched_eval(script, numkeys, *args):
            key = args[0] if isinstance(args[0], str) else args[0].decode()
            val = args[1] if isinstance(args[1], str) else args[1].decode()
            return _enqueue_pure(r_next, key, val)

        # _is_pid_alive를 항상 False로 mock → stale 감지 활성화
        with patch.object(queue_mod, "_is_pid_alive", return_value=False), \
             patch.object(r_next, "eval", side_effect=patched_eval):
            success = queue_mod.acquire_merge_turn(
                r_next, runner_id=next_runner, repo_id=repo_id, timeout=10
            )

        assert success is True, (
            "stale front runner 제거 후 next runner가 turn을 획득해야 함"
        )

        # 최종 큐 상태: stale_runner가 없고 next_runner만 있어야 함
        queue_contents = [
            item.decode() if isinstance(item, bytes) else item
            for item in r_next.lrange(queue_key, 0, -1)
        ]
        assert stale_runner not in queue_contents, (
            f"stale_runner should be removed, queue={queue_contents}"
        )
        assert next_runner in queue_contents, (
            f"next_runner should be in queue, queue={queue_contents}"
        )
