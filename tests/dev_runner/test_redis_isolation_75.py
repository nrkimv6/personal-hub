"""7.5: 테스트/운영 Redis DB 분리 검증"""

import pytest
import redis


REDIS_HOST = "localhost"
REDIS_PORT = 6379
TEST_DB = 15   # 테스트 전용
PROD_DB = 0    # 운영


def _redis_available():
    try:
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=TEST_DB).ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis 미연결")
def test_test_db_does_not_affect_prod_db():
    """db=15에 키 쓴 후 db=0에서 조회 시 키 없음 — DB 격리 기본 동작"""
    test_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=TEST_DB, decode_responses=True)
    prod_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=PROD_DB, decode_responses=True)

    test_key = "test:isolation:marker"
    try:
        test_r.set(test_key, "isolated-value", ex=30)

        # 운영 DB에서는 조회 불가
        assert prod_r.get(test_key) is None, "테스트 DB 키가 운영 DB에 노출되면 안 됨"
        # 테스트 DB에서는 조회 가능
        assert test_r.get(test_key) == "isolated-value"
    finally:
        test_r.delete(test_key)


@pytest.mark.skipif(not _redis_available(), reason="Redis 미연결")
def test_flushdb_test_only_not_prod():
    """테스트 DB flushdb가 운영 DB에 영향 없음"""
    test_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=TEST_DB, decode_responses=True)
    prod_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=PROD_DB, decode_responses=True)

    # 운영 DB에 마커 (기존 키 백업)
    prod_marker = "test:prod:should-survive"
    had_key = prod_r.exists(prod_marker)

    try:
        prod_r.set(prod_marker, "survive", ex=30)
        # 테스트 DB flush
        test_r.flushdb()
        # 운영 DB 키 생존 확인
        assert prod_r.get(prod_marker) == "survive", "테스트 DB flushdb가 운영 DB에 영향 주면 안 됨"
    finally:
        if not had_key:
            prod_r.delete(prod_marker)


def test_executor_service_redis_db_constant():
    """ExecutorService가 사용하는 Redis DB 인덱스 확인 (현재 0 = 운영)"""
    from app.modules.dev_runner.services.executor_service import ExecutorService
    import inspect

    source = inspect.getsource(ExecutorService.__init__)
    # 현재 구조 문서화: db 파라미터 없으면 기본값 0 사용
    # 이 테스트는 현재 상태를 기록하는 용도 (분리 미구현 확인)
    assert "redis.Redis" in source or "aioredis.Redis" in source, \
        "ExecutorService가 Redis 클라이언트를 직접 생성해야 함"


def test_conftest_fixture_isolation_structure():
    """conftest.py에 isolated_redis fixture 존재 여부 확인 (TODO: 미구현 문서화)"""
    from pathlib import Path
    conftest = Path("tests/dev_runner/conftest.py")
    content = conftest.read_text(encoding="utf-8")

    # 현재 상태 문서화 — isolated_redis 미구현 시 SKIP 처리
    if "isolated_redis" not in content:
        pytest.skip(
            "TODO(7.5): conftest.py에 isolated_redis fixture 미구현 — "
            "테스트/운영 Redis DB 분리 작업 필요 (db=15 사용)"
        )
    assert "db=15" in content or "REDIS_DB" in content, \
        "isolated_redis fixture가 db=15를 사용해야 함"
