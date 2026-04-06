"""Redis 좀비 연결 감지 및 정리 TC.

Phase T1: RIGHT-BICEP 기반 단위 테스트
Phase T3: 실제 Redis 통합 테스트 (Redis 미가용 시 skip)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.shared.redis.cleanup import (
    _is_zombie,
    get_zombie_connections,
    kill_zombie_connections,
    kill_zombie_connections_sync,
)
from app.shared.redis.cleanup_scheduler import RedisCleanupScheduler


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _make_conn(**kwargs) -> dict:
    """CLIENT LIST mock 연결 dict 생성."""
    base = {
        "id": "1",
        "addr": "127.0.0.1:12345",
        "idle": "10",
        "flags": "N",
        "cmd": "get",
        "sub": "0",
        "psub": "0",
    }
    base.update(kwargs)
    return base


def _make_mock_redis(connections: list[dict]) -> AsyncMock:
    client = AsyncMock()
    client.client_list = AsyncMock(return_value=connections)
    client.client_kill_filter = AsyncMock(return_value=1)
    return client


# ─── Phase T1: _is_zombie 유닛 ────────────────────────────────────────────────

class TestIsZombie:
    def test_right_normal_connection_not_zombie(self):
        """R(Right): 정상 연결(N flags, cmd=get, idle 낮음)은 좀비 아님."""
        c = _make_conn(idle="10", flags="N", cmd="get")
        assert _is_zombie(c, 300) is False

    def test_right_subscriber_high_idle_no_active_channels_is_zombie(self):
        """R(Right): flags=S, idle=400, sub=0 → 좀비."""
        c = _make_conn(idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        assert _is_zombie(c, 300) is True

    def test_boundary_idle_exactly_threshold_not_zombie(self):
        """B(Boundary): idle == threshold → 좀비 아님 (strictly greater)."""
        c = _make_conn(idle="300", flags="S", cmd="subscribe", sub="0", psub="0")
        assert _is_zombie(c, 300) is False

    def test_boundary_idle_one_over_threshold_is_zombie(self):
        """B(Boundary): idle == threshold + 1 → 좀비."""
        c = _make_conn(idle="301", flags="S", cmd="subscribe", sub="0", psub="0")
        assert _is_zombie(c, 300) is True

    def test_boundary_non_subscriber_high_idle_not_zombie(self):
        """B(Boundary): flags=N, idle=999, cmd=get → 좀비 아님 (subscriber 아님)."""
        c = _make_conn(idle="999", flags="N", cmd="get")
        assert _is_zombie(c, 300) is False

    def test_boundary_active_sub_high_idle_not_zombie(self):
        """B(Boundary): sub=1, psub=2, idle=999 → 좀비 아님 (활성 구독 채널 존재)."""
        c = _make_conn(idle="999", flags="S", cmd="subscribe", sub="1", psub="2")
        assert _is_zombie(c, 300) is False

    def test_right_zero_sub_high_idle_is_zombie(self):
        """R(Right): sub=0, psub=0, idle=400, flags=S → 좀비 (구독 채널 없는 subscriber)."""
        c = _make_conn(idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        assert _is_zombie(c, 300) is True

    def test_right_psubscribe_cmd_high_idle_is_zombie(self):
        """R(Right): cmd=psubscribe, idle=400, sub=0, psub=0 → 좀비."""
        c = _make_conn(idle="400", flags="N", cmd="psubscribe", sub="0", psub="0")
        assert _is_zombie(c, 300) is True


# ─── Phase T1: get_zombie_connections ─────────────────────────────────────────

class TestGetZombieConnections:
    @pytest.mark.asyncio
    async def test_right_empty_when_no_zombies(self):
        """R(Right): 정상 연결만 있을 때 빈 리스트 반환."""
        client = _make_mock_redis([_make_conn(idle="10", flags="N", cmd="get")])
        result = await get_zombie_connections(client, idle_threshold=300)
        assert result == []

    @pytest.mark.asyncio
    async def test_right_detects_idle_subscriber(self):
        """R(Right): idle=400, flags=S, sub=0 → 좀비 감지."""
        conn = _make_conn(idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        client = _make_mock_redis([conn])
        result = await get_zombie_connections(client, idle_threshold=300)
        assert len(result) == 1
        assert result[0]["id"] == "1"
        assert result[0]["idle"] == 400

    @pytest.mark.asyncio
    async def test_boundary_mixed_connections(self):
        """B(Boundary): 정상 + 좀비 혼재 시 좀비만 반환."""
        normal = _make_conn(id="1", idle="10", flags="N")
        zombie = _make_conn(id="2", idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        active_sse = _make_conn(id="3", idle="999", flags="S", cmd="subscribe", sub="1", psub="0")
        client = _make_mock_redis([normal, zombie, active_sse])
        result = await get_zombie_connections(client, idle_threshold=300)
        assert len(result) == 1
        assert result[0]["id"] == "2"


# ─── Phase T1: kill_zombie_connections ────────────────────────────────────────

class TestKillZombieConnections:
    @pytest.mark.asyncio
    async def test_right_dry_run_no_kill(self):
        """R(Right): dry_run=True → CLIENT KILL 호출 안 됨, found > 0, killed == 0."""
        conn = _make_conn(idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        client = _make_mock_redis([conn])
        result = await kill_zombie_connections(client, idle_threshold=300, dry_run=True)
        assert result["found"] == 1
        assert result["killed"] == 0
        assert result["errors"] == []
        client.client_kill_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_right_executes_kill(self):
        """R(Right): dry_run=False, 좀비 1건 → client_kill_filter 호출 1회, killed=1."""
        conn = _make_conn(id="42", idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        client = _make_mock_redis([conn])
        result = await kill_zombie_connections(client, idle_threshold=300, dry_run=False)
        assert result["found"] == 1
        assert result["killed"] == 1
        assert result["errors"] == []
        client.client_kill_filter.assert_called_once_with(_id="42")

    @pytest.mark.asyncio
    async def test_error_partial_failure(self):
        """E(Error): 좀비 2건 중 두 번째 kill 실패 → killed=1, errors=['...'], 예외 전파 없음."""
        conn1 = _make_conn(id="1", idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        conn2 = _make_conn(id="2", idle="400", flags="S", cmd="subscribe", sub="0", psub="0")
        client = _make_mock_redis([conn1, conn2])
        client.client_kill_filter = AsyncMock(side_effect=[1, Exception("kill failed")])
        result = await kill_zombie_connections(client, idle_threshold=300, dry_run=False)
        assert result["found"] == 2
        assert result["killed"] == 1
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_error_client_list_failure(self):
        """E(Error): client_list() 실패 → {found: 0, killed: 0, errors: ['...']} 반환."""
        client = AsyncMock()
        client.client_list = AsyncMock(side_effect=Exception("connection refused"))
        result = await kill_zombie_connections(client, idle_threshold=300)
        assert result["found"] == 0
        assert result["killed"] == 0
        assert len(result["errors"]) == 1


# ─── Phase T1: RedisCleanupScheduler ─────────────────────────────────────────

class TestRedisCleanupScheduler:
    @pytest.mark.asyncio
    async def test_right_startup_uses_low_threshold(self):
        """R(Right): 첫 실행 시 startup_idle_threshold=10으로 호출 확인."""
        scheduler = RedisCleanupScheduler(
            interval=300,
            startup_idle_threshold=10,
            normal_idle_threshold=300,
        )
        calls = []

        async def fake_run_once(idle_threshold):
            calls.append(idle_threshold)
            if len(calls) >= 1:
                raise asyncio.CancelledError()

        scheduler._run_once = fake_run_once

        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_cleanup_loop()

        assert calls[0] == 10

    @pytest.mark.asyncio
    async def test_right_periodic_uses_normal_threshold(self):
        """R(Right): sleep 후 두 번째 실행 시 normal_idle_threshold=300 호출 확인."""
        scheduler = RedisCleanupScheduler(
            interval=0,  # sleep=0으로 즉시 주기 실행
            startup_idle_threshold=10,
            normal_idle_threshold=300,
        )
        calls = []

        async def fake_run_once(idle_threshold):
            calls.append(idle_threshold)

        scheduler._run_once = fake_run_once

        # 태스크로 실행 후 2회 호출 후 취소
        task = asyncio.create_task(scheduler.run_cleanup_loop())
        # 이벤트 루프를 한 번 돌려 2회 실행되도록 기다림
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(calls) >= 2
        assert calls[0] == 10   # startup
        assert calls[1] == 300  # periodic

    @pytest.mark.asyncio
    async def test_error_redis_none_skips_gracefully(self):
        """E(Error): RedisClient.get_client() → None 시 예외 없이 skip."""
        scheduler = RedisCleanupScheduler()
        with patch("app.shared.redis.cleanup_scheduler.RedisClient") as mock_rc:
            mock_rc.get_client = AsyncMock(return_value=None)
            # None 반환 시 예외 없이 정상 완료
            await scheduler._run_once(idle_threshold=300)


# ─── Phase T3: 실제 Redis 통합 테스트 ─────────────────────────────────────────

@pytest.fixture
def real_redis_client():
    """실제 Redis 연결 (미가용 시 skip)."""
    import redis.asyncio as aioredis
    client = aioredis.Redis(
        host="localhost", port=6379,
        decode_responses=True, socket_connect_timeout=2,
    )
    yield client
    # 정리
    try:
        asyncio.run(client.aclose())
    except Exception:
        pass


@pytest.mark.asyncio
async def test_cleanup_real_redis_client_list(real_redis_client):
    """T3: 실제 Redis CLIENT LIST 파싱 정상 동작 확인."""
    try:
        await real_redis_client.ping()
    except Exception:
        pytest.skip("Redis 미가용")

    connections = await real_redis_client.client_list()
    assert isinstance(connections, list)
    if connections:
        c = connections[0]
        assert "id" in c
        assert "idle" in c
        assert "flags" in c


@pytest.mark.asyncio
async def test_cleanup_real_redis_no_zombies(real_redis_client):
    """T3: 실제 Redis에 kill_zombie_connections() 실행 → 좀비 없으면 killed=0."""
    try:
        await real_redis_client.ping()
    except Exception:
        pytest.skip("Redis 미가용")

    result = await kill_zombie_connections(real_redis_client, idle_threshold=300, dry_run=True)
    assert "found" in result
    assert "killed" in result
    assert result["killed"] == 0  # dry_run이므로 항상 0


def test_cleanup_sync_wrapper():
    """T3: kill_zombie_connections_sync() 실제 Redis 호출 → 정상 반환 확인."""
    try:
        import redis as syncredis
        r = syncredis.Redis(host="localhost", port=6379, socket_connect_timeout=2)
        r.ping()
        r.close()
    except Exception:
        pytest.skip("Redis 미가용")

    result = kill_zombie_connections_sync(dry_run=True)
    assert "found" in result
    assert "killed" in result
    assert result["errors"] == [] or isinstance(result["errors"], list)
