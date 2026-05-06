"""
test_reconnect_orphan_76.py - _reconnect_surviving_runners() 고아 키 탐색 단위테스트

active_runners set에 없지만 runners:*:status 키가 존재하는 고아 케이스를 검증한다.
fakeredis 사용 (설치되지 않은 경우 skip).
"""
import sys
import pytest
from unittest.mock import patch

from tests.dev_runner._path_helpers import load_listener_module

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")

# 상수 (listener와 동일)
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"

def make_fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def seed_orphan(r, runner_id, pid, branch="main", status="running"):
    """active_runners set에 추가하지 않고 키만 직접 생성 (고아 시뮬레이션)."""
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
    # sadd 하지 않음 → active_runners에 없음


def seed_active(r, runner_id, pid, branch="main", status="running"):
    """정상 active_runners에 등록된 runner."""
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", str(pid))
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", branch)
    r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", status)
    r.sadd(ACTIVE_RUNNERS_KEY, runner_id)


class TestOrphanScan:
    """고아 키 탐색 로직 검증."""

    def _run_reconnect(self, r, alive_pids=None, identity_matches=True):
        """_reconnect_surviving_runners를 fakeredis + 모킹으로 실행.

        Returns:
            (cleanup_calls, attach_calls): 호출된 runner_id 목록
        """
        mod = load_listener_module("dev_runner_command_listener_test_mod")
        process_utils_mod = sys.modules["_dr_process_utils"]
        state_mod = sys.modules["_dr_state"]
        state_mod.get_running_processes().clear()
        state_mod.get_running_log_files().clear()
        state_mod.get_stream_threads().clear()
        state_mod.get_cleanup_done().clear()
        state_mod.get_dead_process_first_seen().clear()
        state_mod.get_zombie_first_seen().clear()
        alive = set(alive_pids or [])
        cleanup_calls = []
        attach_calls = []

        def fake_is_alive(pid):
            return pid in alive

        def fake_cleanup(runner_id, redis_client, reason="process_cleanup"):
            cleanup_calls.append(runner_id)
            # 실제 키 삭제도 수행 (후속 scan이 동일 키를 보지 않도록)
            keys = list(redis_client.scan_iter(f"{RUNNER_KEY_PREFIX}:{runner_id}:*"))
            if keys:
                redis_client.delete(*keys)
            redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)

        def fake_attach(runner_id, pid, redis_client):
            attach_calls.append(runner_id)

        with (
            patch.object(process_utils_mod, "_is_pid_alive", side_effect=fake_is_alive),
            patch.object(process_utils_mod, "_runner_identity_matches", return_value=(identity_matches, "identity_match" if identity_matches else "process_cmdline_mismatch")),
            patch.object(process_utils_mod, "_cleanup_process_state", side_effect=fake_cleanup),
            patch.object(process_utils_mod, "_attach_to_running_process", side_effect=fake_attach),
        ):
            mod._reconnect_surviving_runners(r)

        return cleanup_calls, attach_calls

    def test_orphan_dead_pid_is_cleaned_up(self):
        """고아 키(active_runners 외)의 PID가 dead → cleanup 호출."""
        r = make_fake_redis()
        seed_orphan(r, "orphan-001", 99999)

        cleanup_calls, attach_calls = self._run_reconnect(r, alive_pids=set())

        assert "orphan-001" in cleanup_calls
        assert "orphan-001" not in attach_calls

    def test_orphan_alive_pid_is_reattached(self):
        """고아 키의 PID가 alive → attach 호출."""
        r = make_fake_redis()
        seed_orphan(r, "orphan-002", 12345)
        r.set(f"{RUNNER_KEY_PREFIX}:orphan-002:subprocess_heartbeat", "alive", ex=120)

        cleanup_calls, attach_calls = self._run_reconnect(r, alive_pids={12345})

        assert "orphan-002" in attach_calls
        assert "orphan-002" not in cleanup_calls

    def test_orphan_alive_pid_identity_mismatch_is_cleaned_up(self):
        """고아 키의 PID가 alive여도 identity mismatch면 cleanup 호출."""
        r = make_fake_redis()
        seed_orphan(r, "orphan-identity-mismatch", 12345)
        r.set(f"{RUNNER_KEY_PREFIX}:orphan-identity-mismatch:subprocess_heartbeat", "alive", ex=120)

        cleanup_calls, attach_calls = self._run_reconnect(
            r,
            alive_pids={12345},
            identity_matches=False,
        )

        assert "orphan-identity-mismatch" in cleanup_calls
        assert "orphan-identity-mismatch" not in attach_calls

    def test_active_runner_not_double_processed(self):
        """active_runners에 있는 runner는 고아 스캔에서 중복 처리되지 않는다."""
        r = make_fake_redis()
        seed_active(r, "active-001", 88888)

        cleanup_calls, _ = self._run_reconnect(r, alive_pids=set())

        # active-001은 1번만 처리
        assert cleanup_calls.count("active-001") == 1

    def test_orphan_no_pid_key_is_cleaned_up(self):
        """고아 키에 PID 필드가 없어도 cleanup 호출."""
        r = make_fake_redis()
        # status 키만 있고 pid 없음
        r.set(f"{RUNNER_KEY_PREFIX}:orphan-003:status", "running")
        r.set(f"{RUNNER_KEY_PREFIX}:orphan-003:branch", "test_branch")

        cleanup_calls, _ = self._run_reconnect(r, alive_pids=set())

        assert "orphan-003" in cleanup_calls

    def test_orphan_invalid_pid_is_cleaned_up(self):
        """고아 키의 PID 값이 잘못된 형식 → cleanup 호출."""
        r = make_fake_redis()
        seed_orphan(r, "orphan-004", "not-a-number")

        cleanup_calls, _ = self._run_reconnect(r, alive_pids=set())

        assert "orphan-004" in cleanup_calls

    def test_no_orphans_no_extra_cleanup(self):
        """고아 키 없으면 orphan scan cleanup 없음."""
        r = make_fake_redis()
        seed_active(r, "active-002", 77777)

        cleanup_calls, attach_calls = self._run_reconnect(r, alive_pids=set())

        # active-002만 1번 cleanup
        assert cleanup_calls == ["active-002"]
        assert attach_calls == []

    def test_empty_redis_no_error(self):
        """Redis가 비어있을 때 에러 없이 종료."""
        r = make_fake_redis()

        cleanup_calls, attach_calls = self._run_reconnect(r, alive_pids=set())

        assert cleanup_calls == []
        assert attach_calls == []

    def test_multiple_orphans_all_cleaned(self):
        """여러 고아 키가 모두 정리된다."""
        r = make_fake_redis()
        for i in range(3):
            seed_orphan(r, f"orphan-multi-{i}", 50000 + i)

        cleanup_calls, _ = self._run_reconnect(r, alive_pids=set())

        for i in range(3):
            assert f"orphan-multi-{i}" in cleanup_calls
