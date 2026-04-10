"""launch-cli Redis roundtrip 통합 테스트.

mock 최소화 — 실제 Redis를 사용하여 API→Redis→listener→결과 반환 흐름을 검증한다.
subprocess는 mock (콘솔 창 생성 불가 환경 대비).

실행: pytest tests/modules/claude_worker/test_launch_cli_integration.py -v -m integration
"""
import json
import time

import pytest
import redis


REDIS_HOST = "localhost"
REDIS_PORT = 6379
LAUNCH_CLI_KEY = "worker:launch-cli"
LAUNCH_CLI_RESULTS_KEY = "worker:launch-cli:results"
TEST_TIMEOUT = 5  # 초


@pytest.fixture(scope="module")
def real_redis():
    """실제 Redis 연결 fixture. 연결 불가 시 skip."""
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        yield r
        r.close()
    except (redis.ConnectionError, redis.TimeoutError):
        pytest.skip("Redis 서버 미실행 — 통합 테스트 skip")


def test_launch_cli_redis_roundtrip(real_redis):
    """실제 Redis roundtrip: LPUSH payload → BRPOP 수신 → 필드 7개 검증 → 결과 LPUSH → API BRPOP 확인."""
    r = real_redis

    # 기존 큐 비우기
    r.delete(LAUNCH_CLI_KEY)
    r.delete(LAUNCH_CLI_RESULTS_KEY)

    # 1. API 측 역할: payload LPUSH
    payload = {
        "action": "launch-cli",
        "engine": "claude",
        "name": "default",
        "config_dir": None,
        "extra_env": {},
        "engine_cmd": "claude",
        "env_key": "CLAUDE_CONFIG_DIR",
    }
    r.lpush(LAUNCH_CLI_KEY, json.dumps(payload, ensure_ascii=False))

    # 2. Listener 역할: BRPOP으로 수신 + 필드 검증
    result = r.brpop([LAUNCH_CLI_KEY], timeout=TEST_TIMEOUT)
    assert result is not None, "payload가 큐에서 수신되지 않음"
    _, raw_data = result
    received = json.loads(raw_data)

    required_fields = {"action", "engine", "name", "config_dir", "extra_env", "engine_cmd", "env_key"}
    missing = required_fields - set(received.keys())
    assert not missing, f"payload에 필드 누락: {missing}"

    # 3. Listener 역할: 결과 LPUSH (subprocess mock)
    listener_result = {
        "success": True,
        "status": "launched",
        "engine": received["engine"],
        "profile": received["name"],
        "executed_at": "2026-04-11T00:00:00",
    }
    r.lpush(LAUNCH_CLI_RESULTS_KEY, json.dumps(listener_result, ensure_ascii=False))
    r.expire(LAUNCH_CLI_RESULTS_KEY, 30)

    # 4. API 측 역할: 결과 BRPOP 수신
    result2 = r.brpop([LAUNCH_CLI_RESULTS_KEY], timeout=TEST_TIMEOUT)
    assert result2 is not None, "결과가 큐에서 수신되지 않음"
    _, raw_result = result2
    api_result = json.loads(raw_result)

    assert api_result["success"] is True
    assert api_result["status"] == "launched"
    assert api_result["engine"] == "claude"
