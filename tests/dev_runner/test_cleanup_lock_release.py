"""
TC: _cleanup_process_state에서 merge lock 안전 해제 단위 테스트

Phase T1 TC:
- test_cleanup_calls_release_merge_lock_R: cleanup → release_merge_lock 1회 호출 (RIGHT)
- test_cleanup_release_ignores_non_owner_B: 소유자 불일치 시 lock 유지 (BOUNDARY)
- test_cleanup_release_exception_does_not_block_E: release 예외 발생해도 cleanup 계속 (ERROR)
- test_stale_lock_ttl_expiry_E: TTL 만료 후 다른 runner acquire 성공 (ERROR)
- test_cleanup_uses_per_repo_queue_key_R: 글로벌 키 아닌 per-repo 큐 키 사용 (RIGHT)
"""
import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import redis
from tests.dev_runner.conftest import attach_default_redis_behaviors

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

SCRIPTS_DIR = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
_PLAN_RUNNER_DIR = SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

REDIS_DB = 15

# _dr_process_utils 로드 (의존성 mock 처리)
_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_process_utils():
    import importlib
    sys.modules["listener_noise_filter"] = _mock_noise
    import _dr_process_utils
    importlib.reload(_dr_process_utils)
    return _dr_process_utils


@pytest.fixture(autouse=True)
def restore_real_merge_queue():
    """sys.modules["merge_queue"] 오염 방어.

    test_post_merge_done_integration.py 등이 모듈 수준에서
    sys.modules["merge_queue"]를 잘못된 키를 반환하는 mock으로 교체한다.
    이 fixture는 각 테스트 전에 실제 merge_queue.py를 로드하여 sys.modules를 복원한다.
    """
    spec = importlib.util.spec_from_file_location("merge_queue", _PLAN_RUNNER_DIR / "merge_queue.py")
    real_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_mod)
    old = sys.modules.get("merge_queue")
    sys.modules["merge_queue"] = real_mod
    yield
    if old is None:
        sys.modules.pop("merge_queue", None)
    else:
        sys.modules["merge_queue"] = old


@pytest.fixture
def redis_client():
    if HAS_FAKEREDIS:
        r = fakeredis.FakeRedis(decode_responses=True)
        _patch_eval_for_fakeredis(r)
    else:
        r = redis.Redis(host="localhost", port=6379, db=REDIS_DB, decode_responses=True)
    for key in r.scan_iter("plan-runner:merge-queue*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-turn*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:runners*"):
        r.delete(key)
    yield r
    for key in r.scan_iter("plan-runner:merge-queue*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:merge-turn*"):
        r.delete(key)
    for key in r.scan_iter("plan-runner:runners*"):
        r.delete(key)


def _patch_eval_for_fakeredis(client):
    """fakeredis에서 merge_queue.acquire_merge_turn가 사용하는 eval을 간단히 에뮬레이트."""
    original_eval = client.eval

    def _eval(script, numkeys, *args):
        if numkeys != 1 or not args:
            return original_eval(script, numkeys, *args)
        key = args[0]
        value = args[1] if len(args) > 1 else None
        items = client.lrange(key, 0, -1)
        if value in items:
            return 0
        client.rpush(key, value)
        return 1

    client.eval = _eval


class TestCleanupLockRelease:
    def test_cleanup_calls_release_merge_lock_R(self):
        """R(Right): _cleanup_process_state 호출 시 release_merge_lock 1회 호출"""
        mock_redis = attach_default_redis_behaviors(MagicMock())
        mock_redis.get.return_value = None

        with patch("merge_queue.release_merge_turn") as mock_release, \
             patch("merge_queue._get_repo_id", return_value="test-repo"), \
             patch("merge_queue.get_queue_key", return_value="plan-runner:merge-queue:test-repo"):
            pu = _load_process_utils()
            # merge 보호 가드 비활성화 (reason이 reconnect_ 아님)
            pu._cleanup_process_state("runner1", mock_redis, reason="process_exit")

        mock_release.assert_called_once()

    def test_cleanup_release_ignores_non_owner_B(self, redis_client):
        """B(Boundary): runner_a가 lock 보유 → runner_b cleanup → lock은 runner_a 소유 유지"""
        from merge_queue import acquire_merge_turn, get_queue_key

        # runner_a가 lock 획득 (큐 선두 = 소유자)
        ok = acquire_merge_turn(redis_client, "runner-a", repo_id="test-repo", timeout=3, queue_ttl=30)
        assert ok is True
        assert redis_client.lindex(get_queue_key("test-repo"), 0) == "runner-a"

        # runner_b cleanup → runner_a lock에 영향 없음
        mock_redis = attach_default_redis_behaviors(MagicMock())
        mock_redis.get.return_value = None
        with patch("merge_queue.release_merge_turn") as mock_release, \
             patch("merge_queue._get_repo_id", return_value="test-repo"), \
             patch("merge_queue.get_queue_key", return_value="plan-runner:merge-queue:test-repo"):
            pu = _load_process_utils()
            pu._cleanup_process_state("runner-b", mock_redis, reason="process_exit")

        # release_merge_lock이 호출됐지만 소유자 불일치 → 실물 Redis에서 runner-a 큐 선두 유지됨
        assert redis_client.lindex(get_queue_key("test-repo"), 0) == "runner-a"

    def test_cleanup_release_exception_does_not_block_E(self):
        """E(Error): release_merge_lock 예외 발생 → cleanup 나머지 로직 정상 실행"""
        mock_redis = attach_default_redis_behaviors(MagicMock())
        mock_redis.get.return_value = None

        with patch("merge_queue.release_merge_turn", side_effect=RuntimeError("redis down")), \
             patch("merge_queue._get_repo_id", return_value="test-repo"), \
             patch("merge_queue.get_queue_key", return_value="plan-runner:merge-queue:test-repo"):
            pu = _load_process_utils()
            # 예외 없이 완료되어야 함
            pu._cleanup_process_state("runner1", mock_redis, reason="process_exit")

        # lrem은 여전히 호출됨 (큐 정리 계속)
        mock_redis.lrem.assert_called()

    def test_stale_lock_ttl_expiry_E(self, redis_client):
        """E(Error): queue_ttl=2초 → 3초 후 큐 키 만료 → 다른 runner acquire 성공"""
        from merge_queue import acquire_merge_turn

        ok = acquire_merge_turn(redis_client, "runner-stale", repo_id="test-repo", timeout=3, queue_ttl=2)
        assert ok is True

        # cleanup 없이 queue_ttl 만료 대기
        time.sleep(3)

        ok2 = acquire_merge_turn(redis_client, "runner-new", repo_id="test-repo", timeout=3, queue_ttl=10)
        assert ok2 is True

    def test_cleanup_uses_per_repo_queue_key_R(self):
        """R(Right): cleanup이 per-repo 큐 키 사용 + 글로벌 키에 영향 없음"""
        mock_redis = attach_default_redis_behaviors(MagicMock())
        mock_redis.get.return_value = None
        captured_keys = []

        def capture_lrem(key, count, value):
            captured_keys.append(key)

        mock_redis.lrem.side_effect = capture_lrem

        with patch("merge_queue.release_merge_turn"), \
             patch("merge_queue._get_repo_id", return_value="d:-work-project-tools-monitor-page"), \
             patch("merge_queue.get_queue_key",
                   return_value="plan-runner:merge-queue:d:-work-project-tools-monitor-page"):
            pu = _load_process_utils()
            pu._cleanup_process_state("runner1", mock_redis, reason="process_exit")

        # per-repo 키가 사용됨
        assert any("d:-work-project-tools-monitor-page" in k for k in captured_keys)
        # 글로벌 키 "plan-runner:merge-wait-queue" (suffix 없음)는 미사용
        assert "plan-runner:merge-queue" not in captured_keys
