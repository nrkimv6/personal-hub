"""conftest guard — fakeredis 감지 동작 검증

Phase R:  재현 TC — 수정 전 버그 문서화 (guard가 fakeredis 주입을 차단)
Phase T1: 수정 후 정상 동작 TC
Phase T3: 통합 TC (E2E 없이 통합 검증)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import fakeredis.aioredis

from app.modules.dev_runner.schemas import RunRequest


# ===========================================================
# 헬퍼 픽스처
# ===========================================================

@pytest.fixture
def _fake_redis_conn():
    """ExecutorService.__init__에서 RedisConnection을 fakeredis로 교체.

    self.redis_client = fakeredis.FakeRedis() 가 되도록 conn_mock을 주입한다.
    """
    fake_r = fakeredis.FakeRedis(decode_responses=True)
    fake_async_r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    conn_mock = MagicMock()
    conn_mock.redis_client = fake_r
    conn_mock.async_redis = fake_async_r

    with patch(
        "app.modules.dev_runner.services.executor_service.RedisConnection",
        return_value=conn_mock,
    ):
        yield fake_r, fake_async_r


@pytest.fixture
def _non_fake_redis_conn():
    """ExecutorService.__init__에서 RedisConnection을 일반 Mock(non-fakeredis)으로 교체.

    redis_client이 MagicMock (NOT FakeRedis)이므로 guard가 계속 적용되어야 한다.
    """
    mock_r = MagicMock()           # NOT fakeredis.FakeRedis
    mock_async_r = AsyncMock()

    conn_mock = MagicMock()
    conn_mock.redis_client = mock_r
    conn_mock.async_redis = mock_async_r

    with patch(
        "app.modules.dev_runner.services.executor_service.RedisConnection",
        return_value=conn_mock,
    ):
        yield mock_r, mock_async_r


# ===========================================================
# Phase T3: 재현 TC rename — Phase R에서 이어짐
# 원본: test_guard_blocks_fakeredis_without_env_R
# → rename: test_guard_no_longer_blocks_fakeredis_after_fix_R
# → assertion 변경: guard가 차단 → guard가 통과 (수정 후 동작)
# ===========================================================

@pytest.mark.asyncio
async def test_guard_no_longer_blocks_fakeredis_after_fix_R(
    _fake_redis_conn,
    monkeypatch,
):
    """T3-R: Phase 1 수정 후 — fakeredis 주입 시 guard가 차단하지 않음.

    [수정 전 버그 (Phase R 원본)]:
        _patched_init이 redis_client 타입을 확인하지 않았다.
        fakeredis를 주입해도 PLAN_RUNNER_REDIS_DB=0이면 pytest.fail이 발생했다.

    [수정 후 동작 (이 TC가 검증)]:
        _patched_init이 original_init 호출 후 self.redis_client 타입을 확인한다.
        isinstance(self.redis_client, fakeredis.FakeRedis) → True이면 guard wrapping 스킵.
        PLAN_RUNNER_REDIS_DB=0이더라도 fakeredis 주입 시 start_dev_runner는 래핑되지 않는다.
    """
    from app.modules.dev_runner.services.executor_service import ExecutorService

    # production처럼 보이는 기본값 "0" — 수정 전에는 이것이 차단 원인이었음
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "0")

    svc = ExecutorService()

    # 수정 후: start_dev_runner는 guard(_patched)로 래핑되지 않아야 한다
    assert svc.start_dev_runner.__name__ != "_patched", (
        "수정 후 fakeredis 주입 시 start_dev_runner는 guard로 래핑되지 않아야 한다.\n"
        f"  실제 이름: {svc.start_dev_runner.__name__!r}\n"
        f"  redis_client 타입: {type(svc.redis_client).__name__}\n"
        "  _patched_init이 fakeredis.FakeRedis를 감지하여 guard wrapping을 스킵해야 함."
    )


# ===========================================================
# Phase T1: guard 정상 동작 TC (Phase 1 수정 후 통과해야 함)
# ===========================================================

@pytest.mark.asyncio
async def test_guard_passes_fakeredis_injected_R(
    _fake_redis_conn,
    monkeypatch,
):
    """T1-R: 수정 후 fakeredis 주입 + env 미설정 → guard가 차단하지 않음.

    _patched_init이 redis_client 타입을 감지하여 fakeredis이면 guard를 적용하지 않아야 한다.
    """
    from app.modules.dev_runner.services.executor_service import ExecutorService

    # PLAN_RUNNER_REDIS_DB 기본값 "0" (production처럼 보이지만 fakeredis 사용)
    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "0")

    svc = ExecutorService()

    # guard가 적용되지 않음: start_dev_runner는 원본 메서드 이름 유지
    assert svc.start_dev_runner.__name__ == "start_dev_runner", (
        "fakeredis 주입 시 start_dev_runner는 원본 메서드여야 한다 (guard 미적용).\n"
        f"  실제 이름: {svc.start_dev_runner.__name__!r}\n"
        f"  redis_client 타입: {type(svc.redis_client).__name__}"
    )

    # redis_client가 실제로 FakeRedis인지 확인
    assert isinstance(svc.redis_client, fakeredis.FakeRedis), (
        f"svc.redis_client는 FakeRedis여야 한다. 실제: {type(svc.redis_client).__name__}"
    )


@pytest.mark.asyncio
async def test_guard_blocks_real_redis_db0_B(
    _non_fake_redis_conn,
    monkeypatch,
):
    """T1-B: 실제 Redis(non-fakeredis) + db=0 → guard가 여전히 차단해야 함.

    fakeredis가 아닌 redis_client 사용 시 기존 동작이 유지되어야 한다.
    수정이 기존 guard 로직을 깨뜨리지 않는지 검증.
    """
    from app.modules.dev_runner.services.executor_service import ExecutorService

    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "0")

    svc = ExecutorService()

    # non-fakeredis이면 guard가 여전히 적용되어야 함
    assert svc.start_dev_runner.__name__ == "_patched", (
        "non-fakeredis redis_client 시 start_dev_runner는 guard(_patched)로 래핑되어야 한다.\n"
        f"  실제 이름: {svc.start_dev_runner.__name__!r}\n"
        f"  redis_client 타입: {type(svc.redis_client).__name__}"
    )

    # 실제로 호출 시 pytest.fail이 발생해야 함 (production Redis 보호)
    request = RunRequest(test_source="guard_boundary_real_db0", plan_file="test.md")
    with pytest.raises(pytest.fail.Exception, match="production Redis"):
        await svc.start_dev_runner(request)


@pytest.mark.asyncio
async def test_guard_passes_real_redis_db15_B(
    _non_fake_redis_conn,
    monkeypatch,
):
    """T1-B: 실제 Redis(non-fakeredis) + db=15 → guard가 통과해야 함 (기존 동작 유지).

    PLAN_RUNNER_REDIS_DB=15이면 guard의 db=0 차단 로직을 통과한다.
    non-fakeredis이더라도 db=15이면 guard wrapping은 적용되지만 차단은 하지 않아야 함.
    """
    from app.modules.dev_runner.services.executor_service import ExecutorService

    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")

    svc = ExecutorService()

    # guard wrapping은 적용되어 있음 (non-fakeredis이므로)
    assert svc.start_dev_runner.__name__ == "_patched", (
        "non-fakeredis + db=15 시에도 guard wrapping은 적용되어야 한다."
    )

    # 호출 시 guard가 db=15를 감지하여 차단하지 않음 확인
    request = RunRequest(test_source="guard_boundary_real_db15", plan_file="test.md")

    try:
        await svc.start_dev_runner(request)
    except pytest.fail.Exception as exc:
        pytest.fail(
            f"PLAN_RUNNER_REDIS_DB=15 시 guard가 차단하면 안 됨: {exc}"
        )
    except Exception:
        # 다른 예외(HTTPException, Redis 연결 오류 등)는 허용
        # 중요한 건 pytest.fail.Exception(guard 차단)이 발생하지 않아야 함
        pass


# ===========================================================
# Phase T3: 통합 TC — monkeypatch.setenv 없이 fakeredis 주입
# ===========================================================

@pytest.mark.asyncio
async def test_executor_with_fakeredis_no_env_patch_I(
    _fake_redis_conn,
    monkeypatch,
):
    """T3-I: ExecutorService에 fakeredis 주입 시 monkeypatch.setenv 없이 guard 통과.

    [기존 패턴 (수정 전 필요했던 코드)]:
        monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")  ← 이 줄이 불필요해짐
        service = ExecutorService()
        service.redis_client = fake_redis  ← __init__ 이후 교체

    [수정 후 패턴 (이 TC가 검증)]:
        # PLAN_RUNNER_REDIS_DB 설정 없이 — fakeredis가 __init__에서 자동 감지됨
        service = ExecutorService()  ← _patched_init이 fakeredis를 감지하여 guard 미적용

    참고: fakeredis를 __init__ 후 교체(post-init injection)하는 기존 패턴은
          _patched_init 실행 시점에 아직 fakeredis가 아니므로 여전히 setenv 필요.
          이 TC는 __init__ 중에 fakeredis가 주입되는 경우(RedisConnection 모킹)를 검증.
    """
    from app.modules.dev_runner.services.executor_service import ExecutorService

    # PLAN_RUNNER_REDIS_DB 환경변수 완전 삭제 (기본값 "0"으로 동작)
    monkeypatch.delenv("PLAN_RUNNER_REDIS_DB", raising=False)

    svc = ExecutorService()

    # start_dev_runner가 guard로 래핑되지 않았음을 확인
    assert svc.start_dev_runner.__name__ != "_patched", (
        "fakeredis 주입 시 monkeypatch.setenv 없이도 guard가 차단하지 않아야 한다.\n"
        f"  실제 이름: {svc.start_dev_runner.__name__!r}\n"
        "  _patched_init이 fakeredis.FakeRedis를 감지하여 guard wrapping을 스킵해야 함."
    )

    # redis_client가 fakeredis.FakeRedis임을 확인
    assert isinstance(svc.redis_client, fakeredis.FakeRedis), (
        f"svc.redis_client는 fakeredis.FakeRedis 인스턴스여야 한다. 실제: {type(svc.redis_client).__name__}"
    )
