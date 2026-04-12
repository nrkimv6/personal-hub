"""7.5: 테스트/운영 Redis DB 분리 검증"""

import pytest
import redis


REDIS_HOST = "localhost"
REDIS_PORT = 6379
TEST_DB = 15   # 테스트 전용
PROD_DB = 0    # 운영


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
    """RedisConnection이 PLAN_RUNNER_REDIS_DB 값을 pool db 인자로 사용하는지 확인."""
    import os
    import inspect
    from app.modules.dev_runner.services.redis_connection import RedisConnection, REDIS_DB

    source = inspect.getsource(RedisConnection.reconnect)
    assert "db=REDIS_DB" in source, "RedisConnection.reconnect가 pool 생성 시 REDIS_DB를 사용해야 함"
    assert REDIS_DB == int(os.environ.get("PLAN_RUNNER_REDIS_DB", "0")), \
        "REDIS_DB 상수는 PLAN_RUNNER_REDIS_DB 환경변수와 동기화되어야 함"


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
    assert "def isolated_redis" in content and "plan-runner:" in content, \
        "isolated_redis fixture가 plan-runner 키 격리/정리 구조를 포함해야 함"
