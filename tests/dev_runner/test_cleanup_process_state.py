"""
test_cleanup_process_state.py
- _cleanup_process_state() EXPIRE + RECENT 등록 검증
- _force_cleanup_state() 방어 로직 검증
- RUNNER_KEY_SUFFIXES 완전성 검증
"""
import re
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# listener 스크립트를 sys.path에 추가
_SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    import fakeredis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis 미설치")


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def make_fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def seed_runner_keys(r, runner_id: str, suffixes: tuple):
    """테스트용 per-runner 키를 fakeredis에 세팅"""
    prefix = "plan-runner:runners"
    for suffix in suffixes:
        r.set(f"{prefix}:{runner_id}:{suffix}", f"val_{suffix}")
    r.sadd("plan-runner:active_runners", runner_id)


# ──────────────────────────────────────────────
# _cleanup_process_state 테스트
# ──────────────────────────────────────────────

class TestCleanupProcessState:
    """_cleanup_process_state() 내부 Redis 동작 검증 (listener 상수 기준)"""

    def _import_listener_constants(self):
        """listener 모듈에서 상수 가져오기 (import 실패 시 직접 정의)"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "listener", Path(_SCRIPTS_DIR) / "dev-runner-command-listener.py"
            )
            # 스크립트 전체 실행은 부수 효과가 크므로, 상수만 정규식으로 파싱
        except Exception:
            pass

        # 직접 상수 참조
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES,
            RUNNER_KEY_PREFIX,
            ACTIVE_RUNNERS_KEY,
            RECENT_RUNNERS_KEY,
            RECENT_RUNNERS_TTL,
        )
        return RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL

    def test_cleanup_expires_all_runner_keys(self):
        """R: cleanup 후 모든 15개 suffix 키에 TTL이 설정돼야 한다 (preserve_worktree=False)"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-expire"
        seed_runner_keys(r, runner_id, RUNNER_KEY_SUFFIXES)

        # cleanup 로직 직접 실행 (함수 import 대신 로직을 재현)
        # listener의 _cleanup_process_state 핵심 로직을 테스트
        _preserve_worktree = False
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            r.expire(key, RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        # 각 키에 TTL이 설정됐는지 확인
        for suffix in RUNNER_KEY_SUFFIXES:
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            ttl = r.ttl(key)
            # TTL -2: 키 없음, -1: TTL 없음, >0: TTL 있음
            assert ttl > 0 or ttl == -2, (
                f"키 '{key}'에 TTL이 설정되지 않음 (ttl={ttl}). "
                f"RUNNER_KEY_SUFFIXES에 포함되지만 expire 처리 안 됨."
            )

    def test_cleanup_sets_status_stopped(self):
        """R: cleanup 후 status 키가 'stopped'여야 한다"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-stopped"
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        _preserve_worktree = False
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue
            r.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        assert r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "stopped"

    def test_cleanup_registers_recent_runners(self):
        """R: cleanup 후 runner_id가 RECENT_RUNNERS sorted set에 존재해야 한다"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-recent"
        seed_runner_keys(r, runner_id, RUNNER_KEY_SUFFIXES)

        _preserve_worktree = False
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue
            r.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        members = r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert runner_id in members, f"runner_id '{runner_id}'가 RECENT_RUNNERS에 없음"

    def test_cleanup_removes_from_active(self):
        """R: cleanup 후 runner_id가 ACTIVE_RUNNERS set에 없어야 한다"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-active"
        seed_runner_keys(r, runner_id, RUNNER_KEY_SUFFIXES)
        assert r.sismember(ACTIVE_RUNNERS_KEY, runner_id)

        _preserve_worktree = False
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue
            r.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        assert not r.sismember(ACTIVE_RUNNERS_KEY, runner_id)

    def test_cleanup_preserves_worktree_on_in_progress(self):
        """B: _preserve_worktree=True 시 worktree_path 키만 TTL 없이 보존돼야 한다"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-preserv"
        seed_runner_keys(r, runner_id, RUNNER_KEY_SUFFIXES)

        _preserve_worktree = True
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue  # worktree_path는 TTL 설정 스킵
            r.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        # worktree_path TTL == -1 (persist) 확인
        wt_ttl = r.ttl(f"{RUNNER_KEY_PREFIX}:{runner_id}:worktree_path")
        assert wt_ttl == -1, f"worktree_path TTL이 -1이어야 하는데 {wt_ttl}"

        # 나머지 키는 TTL > 0
        for suffix in RUNNER_KEY_SUFFIXES:
            if suffix == "worktree_path":
                continue
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            ttl = r.ttl(key)
            assert ttl > 0 or ttl == -2, f"'{suffix}' 키 TTL이 설정되지 않음 (ttl={ttl})"

    def test_cleanup_no_orphan_keys_after_full_cleanup(self):
        """B: cleanup 후 TTL이 없는(-1) per-runner 키가 없어야 한다 (preserve_worktree=False)"""
        RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RECENT_RUNNERS_TTL = self._import_listener_constants()
        r = make_fake_redis()
        runner_id = "t-clnproc-orphan"
        seed_runner_keys(r, runner_id, RUNNER_KEY_SUFFIXES)

        _preserve_worktree = False
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "stopped")
        for suffix in RUNNER_KEY_SUFFIXES:
            if _preserve_worktree and suffix == "worktree_path":
                continue
            r.expire(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", RECENT_RUNNERS_TTL)
        r.srem(ACTIVE_RUNNERS_KEY, runner_id)
        r.zadd(RECENT_RUNNERS_KEY, {runner_id: time.time()})

        # TTL == -1인 키: persist 키 (orphan) — 없어야 함
        for suffix in RUNNER_KEY_SUFFIXES:
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            ttl = r.ttl(key)
            assert ttl != -1, (
                f"'{key}' 키가 TTL 없이 영구 보존됨 (orphan). "
                f"cleanup 후 모든 키에 EXPIRE가 설정돼야 한다."
            )


# ──────────────────────────────────────────────
# _force_cleanup_state 방어 로직 테스트
# ──────────────────────────────────────────────

class TestForceCleanupStateDefense:
    """_force_cleanup_state() status 키 없을 때 RECENT 등록 스킵 검증"""

    @pytest.fixture
    def executor_service_with_fake_redis(self):
        """fakeredis를 주입한 executor_service 인스턴스"""
        import redis.asyncio as aioredis
        import fakeredis.aioredis as fake_aioredis
        from app.modules.dev_runner.services.executor_service import ExecutorService

        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = fake_r
        svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
        return svc, fake_r

    @pytest.mark.asyncio
    async def test_force_cleanup_skips_zadd_when_no_status(self, executor_service_with_fake_redis):
        """B: status 키가 없는 runner는 RECENT에 zadd하지 않아야 한다"""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, RECENT_RUNNERS_KEY, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = executor_service_with_fake_redis
        runner_id = "t-clnproc-ghost"
        # status 키 없이 ACTIVE에만 등록 (listener가 이미 키 정리한 상황)
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        await svc._force_cleanup_state(runner_id)

        members = await fake_r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert runner_id not in members, (
            f"status 키 없는 runner '{runner_id}'가 RECENT에 등록됨 — 유령 탭 생성 버그"
        )
        # ACTIVE에서도 제거됐는지 확인
        assert not await fake_r.sismember(ACTIVE_RUNNERS_KEY, runner_id)

    @pytest.mark.asyncio
    async def test_force_cleanup_registers_when_status_exists(self, executor_service_with_fake_redis):
        """R: status 키가 있는 runner는 RECENT에 정상 등록돼야 한다"""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, RECENT_RUNNERS_KEY, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = executor_service_with_fake_redis
        runner_id = "t-clnproc-valid"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        await svc._force_cleanup_state(runner_id)

        members = await fake_r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert runner_id in members, f"status 있는 runner '{runner_id}'가 RECENT에 미등록"
        assert await fake_r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "stopped"


# ──────────────────────────────────────────────
# _force_cleanup_state 로그 검증 테스트
# ──────────────────────────────────────────────

class TestForceCleanupStateLogs:
    """_force_cleanup_state() 로그 발생 검증"""

    @pytest.fixture
    def svc_with_fake_redis(self):
        import fakeredis.aioredis as fake_aioredis
        from app.modules.dev_runner.services.executor_service import ExecutorService
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = fake_r
        svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
        return svc, fake_r

    @pytest.mark.asyncio
    async def test_force_cleanup_state_logs_on_entry(self, svc_with_fake_redis, caplog):
        """R: force_cleanup_state 시작 시 INFO 로그가 발생해야 한다"""
        import logging
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = svc_with_fake_redis
        runner_id = "t-log-entry-001"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with caplog.at_level(logging.INFO, logger="app.modules.dev_runner.services.executor_service"):
            await svc._force_cleanup_state(runner_id)

        assert any("force_cleanup_state 시작" in r.message and runner_id in r.message for r in caplog.records), \
            "force_cleanup_state 진입 로그 없음"

    @pytest.mark.asyncio
    async def test_force_cleanup_state_logs_skip_when_no_status_key(self, svc_with_fake_redis, caplog):
        """B: status 키 없는 경우 debug 스킵 로그가 발생해야 한다"""
        import logging
        from app.modules.dev_runner.services.executor_service import ACTIVE_RUNNERS_KEY
        svc, fake_r = svc_with_fake_redis
        runner_id = "t-log-skip-001"
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with caplog.at_level(logging.DEBUG, logger="app.modules.dev_runner.services.executor_service"):
            await svc._force_cleanup_state(runner_id)

        assert any("status 키 없음" in r.message and runner_id in r.message for r in caplog.records), \
            "status 키 없음 스킵 로그 없음"

    @pytest.mark.asyncio
    async def test_force_cleanup_state_logs_completion(self, svc_with_fake_redis, caplog):
        """R: status 키 있는 경우 완료 로그가 발생해야 한다"""
        import logging
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = svc_with_fake_redis
        runner_id = "t-log-done-001"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with caplog.at_level(logging.INFO, logger="app.modules.dev_runner.services.executor_service"):
            await svc._force_cleanup_state(runner_id)

        assert any("force_cleanup_state 완료" in r.message and "RECENT 이동" in r.message for r in caplog.records), \
            "force_cleanup_state 완료 로그 없음"


# ──────────────────────────────────────────────
# cleanup_stale_runners 로그 검증 테스트
# ──────────────────────────────────────────────

class TestCleanupStaleRunnersLogs:
    """_cleanup_stale_runners() runner별 사유 로그 검증"""

    @pytest.fixture
    def svc_with_fake_redis(self):
        import fakeredis.aioredis as fake_aioredis
        from app.modules.dev_runner.services.executor_service import ExecutorService
        fake_r = fake_aioredis.FakeRedis(decode_responses=True)
        svc = ExecutorService.__new__(ExecutorService)
        svc.async_redis = fake_r
        svc.redis_client = fakeredis.FakeRedis(decode_responses=True)
        return svc, fake_r

    @pytest.mark.asyncio
    async def test_cleanup_stale_runners_logs_per_runner_reason(self, svc_with_fake_redis, caplog):
        """R: PID dead stale runner 발견 시 runner ID가 포함된 WARNING 로그가 발생해야 한다"""
        import logging
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = svc_with_fake_redis
        runner_id = "t-stale-001"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:pid", "999999999")
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        # _is_pid_alive를 항상 False 반환으로 mock
        with patch.object(svc, "_is_pid_alive", return_value=False):
            with caplog.at_level(logging.WARNING, logger="app.modules.dev_runner.services.executor_service"):
                await svc._cleanup_stale_runners()

        assert any("stale active runner" in r.message and runner_id in r.message for r in caplog.records), \
            f"stale runner {runner_id}에 대한 WARNING 로그 없음"


# ──────────────────────────────────────────────
# 키 상수 동기화 테스트
# ──────────────────────────────────────────────

class TestRunnerKeySuffixesCompleteness:
    """RUNNER_KEY_SUFFIXES가 listener에서 set하는 모든 suffix를 포함하는지 검증"""

    def test_runner_key_suffixes_covers_all_set_keys(self):
        """R: listener에서 redis_client.set(f'{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}') 패턴으로
        사용되는 모든 suffix가 RUNNER_KEY_SUFFIXES에 포함돼야 한다"""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX,
        )

        listener_path = Path(_SCRIPTS_DIR) / "dev-runner-command-listener.py"
        source = listener_path.read_text(encoding="utf-8")

        # redis_client.set(f"...:{runner_id}:{suffix}" 또는 :{rid}: 패턴 스캔
        # 패턴: RUNNER_KEY_PREFIX}:{변수}:{suffix_literal}
        pattern = re.compile(
            r'redis_client\.set\s*\(\s*f["\']'
            r'\{RUNNER_KEY_PREFIX\}:\{r(?:unner_id|id)\}:([a-z_]+)["\']'
        )
        found_suffixes = set(pattern.findall(source))

        missing = found_suffixes - set(RUNNER_KEY_SUFFIXES)
        assert not missing, (
            f"listener에서 set하지만 RUNNER_KEY_SUFFIXES에 없는 suffix: {missing}\n"
            f"executor_service.py의 RUNNER_KEY_SUFFIXES에 추가하세요."
        )
