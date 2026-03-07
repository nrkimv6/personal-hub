"""_get_fix_engine 함수 단위 테스트"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# listener 스크립트에서 함수를 직접 import할 수 없으므로 (모듈이 아님)
# 함수를 인라인으로 재정의하여 테스트한다.
# 원본: scripts/dev-runner-command-listener.py:704-719

RUNNER_KEY_PREFIX = "plan-runner:runners"


def _get_fix_engine(redis_client, runner_id: str) -> str:
    """runner의 fix_engine 값을 Redis에서 읽어 반환한다.

    우선순위: fix_engine 키 > engine 키 > "claude" 기본값
    Redis 오류 시 "claude" fallback.
    """
    try:
        value = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:fix_engine")
        if value:
            return value
        value = redis_client.get(f"{RUNNER_KEY_PREFIX}:{runner_id}:engine")
        if value:
            return value
    except Exception:
        pass
    return "claude"


class TestGetFixEngine:
    """_get_fix_engine 함수 테스트"""

    def test_get_fix_engine_right(self):
        """R: fix_engine 키 존재 시 해당 값 반환"""
        redis_mock = MagicMock()
        redis_mock.get.side_effect = lambda key: {
            f"{RUNNER_KEY_PREFIX}:r1:fix_engine": "gemini",
            f"{RUNNER_KEY_PREFIX}:r1:engine": "claude",
        }.get(key)

        result = _get_fix_engine(redis_mock, "r1")
        assert result == "gemini"

    def test_get_fix_engine_boundary_fallback_to_engine(self):
        """B: fix_engine 없고 engine만 있을 때 engine 반환"""
        redis_mock = MagicMock()
        redis_mock.get.side_effect = lambda key: {
            f"{RUNNER_KEY_PREFIX}:r1:fix_engine": None,
            f"{RUNNER_KEY_PREFIX}:r1:engine": "gemini",
        }.get(key)

        result = _get_fix_engine(redis_mock, "r1")
        assert result == "gemini"

    def test_get_fix_engine_error_fallback_to_claude(self):
        """E: 두 키 모두 없을 때 "claude" 기본값 반환"""
        redis_mock = MagicMock()
        redis_mock.get.return_value = None

        result = _get_fix_engine(redis_mock, "r1")
        assert result == "claude"

    def test_get_fix_engine_error_redis_exception(self):
        """E: Redis 연결 오류 시 "claude" fallback"""
        redis_mock = MagicMock()
        redis_mock.get.side_effect = ConnectionError("Redis down")

        result = _get_fix_engine(redis_mock, "r1")
        assert result == "claude"
