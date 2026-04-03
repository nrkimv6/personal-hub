"""_dr_runtime_utils 공통 헬퍼 단위 테스트."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import redis

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry


def test_normalize_exit_reason_right_completed():
    assert _normalize_exit_reason(" completed ") == "completed"


def test_normalize_exit_reason_boundary_none():
    assert _normalize_exit_reason(None) == "error"


def test_publish_with_retry_error_connection_drop():
    mock_redis = MagicMock()
    mock_redis.publish.side_effect = [redis.ConnectionError("drop"), 1]
    mock_redis.ping.return_value = True

    assert _publish_with_retry(mock_redis, "plan-runner:logs:test", "hello") is True
    assert mock_redis.ping.call_count == 1
    assert mock_redis.publish.call_count == 2
