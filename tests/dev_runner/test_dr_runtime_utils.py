"""_dr_runtime_utils 공통 헬퍼 단위 테스트."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import redis
from tests.dev_runner.conftest import attach_default_redis_behaviors

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_PLAN_RUNNER_DIR = _SCRIPTS_DIR / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))

import _dr_runtime_utils
from _dr_runtime_utils import _normalize_exit_reason, _publish_with_retry


def test_normalize_exit_reason_right_completed():
    assert _normalize_exit_reason(" completed ") == "completed"


def test_normalize_exit_reason_boundary_none():
    assert _normalize_exit_reason(None) == "error"


def test_publish_with_retry_error_connection_drop():
    mock_redis = attach_default_redis_behaviors(MagicMock())
    mock_redis.publish.side_effect = [redis.ConnectionError("drop"), 1]
    mock_redis.ping.return_value = True

    assert _publish_with_retry(mock_redis, "plan-runner:logs:test", "hello") is True
    assert mock_redis.ping.call_count == 1
    assert mock_redis.publish.call_count == 2


def test_publish_with_retry_reference_listener_path():
    """listener/runtime modules use the shared publish helper, not local copies."""
    import _dr_plan_runner
    import _dr_process_utils

    assert _dr_plan_runner._publish_with_retry is _dr_runtime_utils._publish_with_retry
    assert _dr_process_utils._publish_with_retry is _dr_runtime_utils._publish_with_retry
    assert _dr_plan_runner._normalize_exit_reason is _dr_runtime_utils._normalize_exit_reason
    assert _dr_process_utils._normalize_exit_reason is _dr_runtime_utils._normalize_exit_reason
