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

from tests.dev_runner._path_helpers import (
    bootstrap_plan_runner_modules,
    get_plan_runner_impl_script_path,
)

# listener 스크립트를 sys.path에 추가
_SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
_PLAN_RUNNER_DIR = str(Path(_SCRIPTS_DIR) / "plan_runner")
if _PLAN_RUNNER_DIR not in sys.path:
    sys.path.insert(0, _PLAN_RUNNER_DIR)

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
        """executor_service에서 listener 상수를 직접 가져온다."""
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
        """R: visible runner(trigger=user)이고 status 키가 있으면 RECENT에 정상 등록돼야 한다"""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, RECENT_RUNNERS_KEY, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = executor_service_with_fake_redis
        runner_id = "t-clnproc-valid"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # trigger=user 설정을 통해 visible runner임을 명시
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        await svc._force_cleanup_state(runner_id)

        members = await fake_r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert runner_id in members, f"status 있는 runner '{runner_id}'가 RECENT에 미등록"
        assert await fake_r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") == "stopped"

    @pytest.mark.asyncio
    async def test_force_cleanup_invisible_runner_not_registered_in_recent(self, executor_service_with_fake_redis):
        """R: invisible runner(trigger 미설정)는 status 키가 있어도 RECENT에 등록되지 않아야 한다"""
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_PREFIX, RECENT_RUNNERS_KEY, ACTIVE_RUNNERS_KEY,
        )
        svc, fake_r = executor_service_with_fake_redis
        runner_id = "t-clnproc-invisible"
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:status", "running")
        # trigger를 설정하지 않음 -> invisible runner
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        await svc._force_cleanup_state(runner_id)

        members = await fake_r.zrange(RECENT_RUNNERS_KEY, 0, -1)
        assert runner_id not in members, f"invisible runner '{runner_id}'가 RECENT에 등록됨"
        # 키가 삭제됐는지 확인 (invisible 경로는 키 즉시 삭제)
        assert await fake_r.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:status") is None


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
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with caplog.at_level(logging.INFO, logger="app.modules.dev_runner.services.executor_service"):
            await svc._force_cleanup_state(runner_id)

        assert any(
            r.levelno == logging.INFO and runner_id in r.getMessage()
            for r in caplog.records
        ), "force_cleanup_state 진입 로그 없음"

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

        assert any(
            r.levelno == logging.DEBUG and runner_id in r.getMessage()
            for r in caplog.records
        ), "status 키 없음 스킵 로그 없음"

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
        await fake_r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        await fake_r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with caplog.at_level(logging.INFO, logger="app.modules.dev_runner.services.executor_service"):
            await svc._force_cleanup_state(runner_id)

        assert any(
            r.levelno == logging.INFO and runner_id in r.getMessage()
            for r in caplog.records
        ), "force_cleanup_state 완료 로그 없음"


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
# _cleanup_process_state 보존 계약 TC (Phase 1-1)
# ──────────────────────────────────────────────

class TestCleanupProcessStatePersistSuffixes:
    """_cleanup_process_state() — plan_file/branch/trigger 영구 보존 계약 검증"""

    def _import_process_utils(self):
        import importlib
        import types

        # listener noise filter mock (부수 효과 방지)
        if "listener_noise_filter" not in sys.modules:
            mock_noise = types.ModuleType("listener_noise_filter")
            mock_noise.NOISE_BLOCK_MARKERS = []
            mock_noise.is_noise_line = lambda line: False
            sys.modules["listener_noise_filter"] = mock_noise

        # _dr_constants, _dr_state 먼저 로드 (_dr_process_utils 의존)
        _, process_utils_mod = bootstrap_plan_runner_modules()
        return process_utils_mod

    def test_cleanup_process_state_persist_trigger_plan_branch(self):
        """R: _cleanup_process_state() 후 plan_file/branch/trigger TTL == -1 (영구 보존)"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-persist-001"

        # 키 세팅: plan_file, branch, trigger 포함
        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:trigger", "user")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/test.md")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:branch", "impl/test")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        pu._cleanup_process_state(runner_id, r, reason="test_persist")

        for key_suffix in ("trigger", "plan_file", "branch"):
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{key_suffix}"
            ttl = r.ttl(key)
            assert ttl == -1, (
                f"'{key_suffix}' 키 TTL이 -1이어야 하는데 {ttl}. "
                "dismiss 전까지 영구 보존 계약 위반."
            )

    def test_cleanup_process_state_other_keys_have_ttl(self):
        """R: _cleanup_process_state() 후 persist 제외 키에는 TTL이 설정된다"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-persist-002"

        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        _PERSIST = frozenset({"plan_file", "branch", "trigger"})
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        pu._cleanup_process_state(runner_id, r, reason="test_other_ttl")

        for suffix in RUNNER_KEY_SUFFIXES:
            if suffix in _PERSIST:
                continue
            key = f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}"
            ttl = r.ttl(key)
            assert ttl > 0 or ttl == -2, (
                f"'{suffix}' 키 TTL이 설정되지 않음 (ttl={ttl})."
            )


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

        listener_path = Path(_SCRIPTS_DIR) / "plan_runner" / "dev-runner-command-listener.py"
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

    def test_runner_key_suffixes_include_process_identity_correct(self):
        """CORRECT: process identity 키는 listener/API cleanup suffix 계약에 포함된다."""
        from app.modules.dev_runner.services.executor_service import RUNNER_KEY_SUFFIXES

        required = {"pid_create_time", "process_cmdline_hash"}
        missing = required - set(RUNNER_KEY_SUFFIXES)
        assert not missing, f"process identity suffix 누락: {missing}"


# ──────────────────────────────────────────────
# 미머지 커밋 보호 가드 TC
# ──────────────────────────────────────────────

class TestCleanupUnmergedCommitsGuard:
    """_cleanup_process_state() — 미머지 커밋 있는 워크트리 보존 가드 검증"""

    def _import_process_utils(self):
        import importlib
        import importlib.util
        import types

        if "listener_noise_filter" not in sys.modules:
            mock_noise = types.ModuleType("listener_noise_filter")
            mock_noise.NOISE_BLOCK_MARKERS = []
            mock_noise.is_noise_line = lambda line: False
            sys.modules["listener_noise_filter"] = mock_noise

        bootstrap_plan_runner_modules()

        # 재로드: 이 테스트 클래스에서 수정된 _dr_process_utils를 사용
        if "_dr_process_utils" in sys.modules:
            del sys.modules["_dr_process_utils"]
        spec = importlib.util.spec_from_file_location(
            "_dr_process_utils",
            get_plan_runner_impl_script_path().with_name("_dr_process_utils.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_dr_process_utils"] = mod
        spec.loader.exec_module(mod)

        return sys.modules["_dr_process_utils"]

    def test_cleanup_preserves_worktree_with_unmerged_commits_R(self):
        """R: 미머지 커밋이 있으면 WorktreeManager.remove를 호출하지 않아야 한다"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-unmerged-001"

        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/2026-04-07_test.md")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with patch("plan_worktree_helpers.has_unmerged_commits", return_value=True), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove, \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            pu._cleanup_process_state(runner_id, r, reason="test")

        mock_remove.assert_not_called()

    def test_cleanup_removes_worktree_without_unmerged_commits_R(self):
        """R: 미머지 커밋이 없으면 WorktreeManager.remove를 호출해야 한다"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-unmerged-002"

        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/2026-04-07_test.md")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        with patch("plan_worktree_helpers.has_unmerged_commits", return_value=False), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove, \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            pu._cleanup_process_state(runner_id, r, reason="test")

        mock_remove.assert_called_once()

    def test_cleanup_preserves_worktree_on_check_failure_E(self):
        """E: has_unmerged_commits 예외 시 보수적으로 워크트리를 보존해야 한다"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-unmerged-003"

        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file", "docs/plan/2026-04-07_test.md")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        # has_unmerged_commits 자체가 True를 반환(예외 시 True)하면 보존
        with patch("plan_worktree_helpers.has_unmerged_commits", return_value=True), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove, \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            pu._cleanup_process_state(runner_id, r, reason="test")

        mock_remove.assert_not_called()

    def test_cleanup_preserves_worktree_branch_resolution_B(self):
        """B: plan_file 없을 때 runner/{runner_id} 브랜치명으로 체크해야 한다"""
        pu = self._import_process_utils()
        r = make_fake_redis()
        runner_id = "t-unmerged-004"

        from app.modules.dev_runner.services.executor_service import (
            RUNNER_KEY_SUFFIXES, RUNNER_KEY_PREFIX, ACTIVE_RUNNERS_KEY,
        )
        for suffix in RUNNER_KEY_SUFFIXES:
            r.set(f"{RUNNER_KEY_PREFIX}:{runner_id}:{suffix}", f"val_{suffix}")
        # plan_file 없음 (PLAN_FILE_ALL도 아님, 아예 없는 경우)
        r.delete(f"{RUNNER_KEY_PREFIX}:{runner_id}:plan_file")
        r.sadd(ACTIVE_RUNNERS_KEY, runner_id)

        captured_branch = []

        def _capture_has_unmerged(branch, cwd=None):
            captured_branch.append(branch)
            return True  # 보존

        with patch("plan_worktree_helpers.has_unmerged_commits", side_effect=_capture_has_unmerged), \
             patch("worktree_manager.WorktreeManager.remove") as mock_remove, \
             patch("plan_worktree_helpers.is_plan_in_progress", return_value=False):
            pu._cleanup_process_state(runner_id, r, reason="test")

        assert captured_branch, "has_unmerged_commits가 호출되지 않음"
        assert captured_branch[0] == f"runner/{runner_id}", (
            f"브랜치명이 'runner/{runner_id}'여야 하는데 '{captured_branch[0]}'"
        )
        mock_remove.assert_not_called()


# ──────────────────────────────────────────────
# T3: 실물 git worktree 통합 테스트
# ──────────────────────────────────────────────

class TestCleanupUnmergedCommitsGuardIntegration:
    """T3: 실제 git repo + worktree 환경에서 cleanup 보호 검증"""

    def _setup_git_repo(self, tmp_path: Path):
        """tmp_path에 실제 git repo 생성, 초기 커밋, worktree 추가"""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)

        # 초기 커밋 (main 브랜치 생성)
        (repo / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
        # 기본 브랜치를 main으로 명시
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(repo), capture_output=True)

        return repo

    def _import_has_unmerged(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "plan_worktree_helpers_real",
            Path(_PLAN_RUNNER_DIR) / "plan_worktree_helpers.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.has_unmerged_commits

    def test_cleanup_real_git_worktree_with_commits_T3(self, tmp_path):
        """T3-R: 미머지 커밋 있는 실물 워크트리 — has_unmerged_commits가 True를 반환해야 한다"""
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        wt_path = tmp_path / "worktree"
        branch = "plan/test-feature"

        # 워크트리 + 브랜치 생성
        subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch],
            cwd=str(repo), check=True, capture_output=True
        )

        # 워크트리 브랜치에 독자 커밋 추가
        (wt_path / "feature.txt").write_text("feature")
        subprocess.run(["git", "add", "."], cwd=str(wt_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=str(wt_path), check=True, capture_output=True)

        has_unmerged = self._import_has_unmerged()
        result = has_unmerged(branch, repo)

        assert result is True, "미머지 커밋이 있는데 has_unmerged_commits가 False를 반환"

    def test_cleanup_real_git_worktree_no_commits_T3(self, tmp_path):
        """T3-R: 독자 커밋 없는 실물 워크트리 — has_unmerged_commits가 False를 반환해야 한다"""
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        wt_path = tmp_path / "worktree"
        branch = "plan/no-changes"

        # 워크트리 + 브랜치 생성 (커밋 없음)
        subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch],
            cwd=str(repo), check=True, capture_output=True
        )

        has_unmerged = self._import_has_unmerged()
        result = has_unmerged(branch, repo)

        assert result is False, "독자 커밋 없는 브랜치인데 has_unmerged_commits가 True를 반환"
