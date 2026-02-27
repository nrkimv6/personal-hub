"""Level 1: 실제 Redis + Listener 프로세스 기동 통합 테스트

실행 조건:
  - Redis 서버 실행 중
  - Listener 스크립트 존재 (scripts/dev-runner-command-listener.py)

실행 명령:
  pytest -m integration tests/dev_runner/test_listener_integration.py -v
"""
import json

import pytest

from tests.dev_runner.conftest_e2e import (
    e2e_redis_cleanup,
    listener_process,
    real_redis,
    test_plan_file,
)

pytestmark = pytest.mark.integration

COMMANDS_KEY = "plan-runner:commands"
RESULTS_KEY = "plan-runner:command_results"
HEARTBEAT_KEY = "plan-runner:listener:heartbeat"


class TestListenerIntegration:
    """Level 1: 실제 Redis + Listener 프로세스 기동 테스트"""

    def test_listener_heartbeat(self, listener_process, real_redis):
        """Listener spawn 후 heartbeat 키가 감지되는가

        listener_process fixture가 이미 10초 내 heartbeat를 대기하므로
        fixture 반환 시점에서 즉시 검증 가능하다.
        """
        heartbeat = real_redis.get(HEARTBEAT_KEY)
        assert heartbeat is not None, "Listener heartbeat 키가 Redis에 존재하지 않음"

    def test_command_roundtrip(self, listener_process, real_redis):
        """LPUSH command → BRPOP result 실제 왕복 성공"""
        command = {"action": "status"}
        real_redis.lpush(COMMANDS_KEY, json.dumps(command))

        result = real_redis.brpop(RESULTS_KEY, timeout=10)
        assert result is not None, "10초 내 Listener 응답 없음"

        payload = json.loads(result[1])
        assert "action" in payload or "status" in payload, (
            f"응답에 예상 필드 없음: {payload}"
        )

    def test_invalid_command_response(self, listener_process, real_redis):
        """잘못된 action 전송 시 에러 응답 반환"""
        command = {"action": "invalid_action_xyz_unknown"}
        real_redis.lpush(COMMANDS_KEY, json.dumps(command))

        result = real_redis.brpop(RESULTS_KEY, timeout=10)
        assert result is not None, "10초 내 에러 응답 없음"

        payload = json.loads(result[1])
        # execute_command는 unknown action에 대해 {"success": False, "message": "Unknown action: ..."}를 반환
        assert payload.get("success") is False, (
            f"잘못된 action에 대해 success=False 기대, 실제: {payload}"
        )
