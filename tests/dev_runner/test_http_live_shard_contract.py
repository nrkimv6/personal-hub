"""Source-level guards for http_live shard isolation."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RESTART_MUTATING_FILES = {
    "tests/dev_runner/test_connection_leak_http.py",
    "tests/dev_runner/test_live_server_http.py",
    "tests/dev_runner/test_live_restart_integration.py",
}

READ_ONLY_WORKTREE_SMOKE_FILES = {
    "tests/dev_runner/test_worktree_cache_e2e.py",
    "tests/dev_runner/test_worktree_list_perf_e2e.py",
}


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_restart_mutating_files_are_not_part_of_read_only_worktree_shard():
    assert RESTART_MUTATING_FILES.isdisjoint(READ_ONLY_WORKTREE_SMOKE_FILES)


def test_read_only_worktree_smoke_does_not_restart_services():
    for path in READ_ONLY_WORKTREE_SMOKE_FILES:
        source = _read(path)
        assert "restart-frontend" not in source
        assert "restart-api" not in source
        assert "redis-cleanup" not in source


def test_read_only_worktree_smoke_waits_for_liveness_before_requests():
    for path in READ_ONLY_WORKTREE_SMOKE_FILES:
        source = _read(path)
        assert "from tests.dev_runner.live_http_readiness import live_get_after_readiness" in source
        assert "return live_get_after_readiness(path, base_url=BASE_URL)" in source


def test_restart_mutating_connection_leak_waits_for_admin_liveness_after_restart():
    source = _read("tests/dev_runner/test_connection_leak_http.py")
    assert "def wait_until_admin_api_ready" in source
    assert source.count("wait_until_admin_api_ready(timeout_seconds=60.0)") >= 2
