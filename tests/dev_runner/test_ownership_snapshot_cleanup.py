"""ownership snapshot lifecycle helper tests."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "plan_runner" / "dev-runner-command-listener.py"

_mock_noise = types.ModuleType("listener_noise_filter")
_mock_noise.NOISE_BLOCK_MARKERS = []
_mock_noise.is_noise_line = lambda line: False


def _load_listener():
    sys.modules["listener_noise_filter"] = _mock_noise
    spec = importlib.util.spec_from_file_location("_listener_snapshot_cleanup", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    mod._running_processes = {}
    mod._running_log_files = {}
    mod._stream_threads = {}
    spec.loader.exec_module(mod)
    return mod


def test_cleanup_stale_ownership_snapshots_removes_inactive_only(tmp_path):
    """R: active runner snapshot은 유지하고 inactive snapshot만 정리한다."""
    listener = _load_listener()
    ownership_dir = tmp_path / "ownership"
    ownership_dir.mkdir()
    active_snapshot = ownership_dir / "runner-active.json"
    stale_snapshot = ownership_dir / "runner-stale.json"
    active_snapshot.write_text("{}", encoding="utf-8")
    stale_snapshot.write_text("{}", encoding="utf-8")

    redis_client = MagicMock()
    redis_client.sismember.side_effect = lambda _key, runner_id: runner_id == "runner-active"

    with patch.object(listener, "OWNERSHIP_SNAPSHOT_DIR", ownership_dir):
        removed = listener._cleanup_stale_ownership_snapshots(redis_client)

    assert removed == 1
    assert active_snapshot.exists()
    assert not stale_snapshot.exists()
