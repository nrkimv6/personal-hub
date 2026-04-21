"""status_actions text-mode subprocess encoding regression tests."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from scripts.services.browser_worker_runtime import status_actions


class _FakeRedisClient:
    def ping(self):
        return True

    def info(self, section=None):
        if section == "server":
            return {"uptime_in_seconds": 1}
        if section == "memory":
            return {"used_memory": 1024}
        if section == "clients":
            return {"connected_clients": 1}
        return {}

    def client_list(self):
        return []

    def close(self):
        return None


def test_redis_status_uses_utf8_text_defaults():
    """R: podman inspect text read는 UTF-8 + replace 계약을 사용한다."""
    fake_redis_module = types.SimpleNamespace(
        Redis=lambda **kwargs: _FakeRedisClient(),
    )
    completed = MagicMock(returncode=0, stdout="true\n", stderr="")

    with patch.dict(sys.modules, {"redis": fake_redis_module}), \
         patch("scripts.services.browser_worker_runtime.status_actions.subprocess.run", return_value=completed) as mock_run:
        status_actions.redis_status(manager=MagicMock())

    kwargs = mock_run.call_args.kwargs
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
