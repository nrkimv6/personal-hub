import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

def test_make_plan_runner_env_base_keys_R():
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PLAN_RUNNER_RUNNER_ID"] == "runner-1"
    assert "REDIS_DB" in env
    assert "CLAUDECODE" not in env

def test_make_plan_runner_env_extra_keys_R():
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1", PLAN_RUNNER_WORK_DIR="/some/path")
    assert env["PLAN_RUNNER_WORK_DIR"] == "/some/path"

def test_make_plan_runner_env_claudecode_removed_B():
    os.environ["CLAUDECODE"] = "1"
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert "CLAUDECODE" not in env
    del os.environ["CLAUDECODE"]

def test_make_plan_runner_env_uses_get_redis_db_R():
    from _dr_constants import set_redis_db
    from _dr_subprocess import _make_plan_runner_env
    set_redis_db(15)
    env = _make_plan_runner_env("test-runner")
    assert env["REDIS_DB"] == "15"
    set_redis_db(0)


def test_make_plan_runner_env_strips_stale_plan_runner_keys_R(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_BRANCH", "impl/stale")
    monkeypatch.setenv("PLAN_RUNNER_WORKTREE_PATH", "D:/stale/worktree")
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert "PLAN_RUNNER_BRANCH" not in env
    assert "PLAN_RUNNER_WORKTREE_PATH" not in env
    assert env["PLAN_RUNNER_RUNNER_ID"] == "runner-1"


def test_make_plan_runner_env_keeps_explicit_extra_only_Co(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_BRANCH", "impl/stale")
    monkeypatch.setenv("PLAN_RUNNER_WORKTREE_PATH", "D:/stale/worktree")
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env(
        "runner-1",
        PLAN_RUNNER_PROJECT_ROOT="D:/work/project/tools/monitor-page",
        PLAN_RUNNER_WORK_DIR="D:/work/project/tools/monitor-page/.worktrees/test",
    )
    assert env["PLAN_RUNNER_PROJECT_ROOT"] == "D:/work/project/tools/monitor-page"
    assert env["PLAN_RUNNER_WORK_DIR"] == "D:/work/project/tools/monitor-page/.worktrees/test"
    assert "PLAN_RUNNER_BRANCH" not in env
    assert "PLAN_RUNNER_WORKTREE_PATH" not in env


def test_make_plan_runner_env_non_plan_runner_env_preserved_B(monkeypatch):
    monkeypatch.setenv("SOME_APP_ENV", "keep-me")
    from _dr_subprocess import _make_plan_runner_env
    env = _make_plan_runner_env("runner-1")
    assert env["SOME_APP_ENV"] == "keep-me"


def test_launch_auto_impl_post_merge_process_env_allowlist_Co(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAN_RUNNER_BRANCH", "impl/stale")
    monkeypatch.setenv("PLAN_RUNNER_WORKTREE_PATH", "D:/stale/worktree")
    from _dr_subprocess import _launch_auto_impl_post_merge_process

    redis_client = MagicMock()
    redis_client.get.return_value = str(tmp_path)
    captured = {}

    def _fake_run(**kwargs):
        captured["env"] = kwargs["env"]
        return {"success": True, "message": "ok", "output": ""}

    with patch("_dr_subprocess._run_subprocess_streaming", side_effect=_fake_run):
        _launch_auto_impl_post_merge_process("runner-allowlist", "D:/plan.md", redis_client)

    env = captured["env"]
    plan_keys = {k for k in env if k.startswith("PLAN_RUNNER_")}
    assert plan_keys == {"PLAN_RUNNER_RUNNER_ID", "PLAN_RUNNER_PROJECT_ROOT", "PLAN_RUNNER_WORK_DIR"}
    assert env["PLAN_RUNNER_WORK_DIR"] == str(tmp_path)


def test_launch_general_merge_resolver_env_keeps_merge_error_R(monkeypatch):
    monkeypatch.setenv("PLAN_RUNNER_BRANCH", "impl/stale")
    monkeypatch.setenv("PLAN_RUNNER_WORKTREE_PATH", "D:/stale/worktree")
    from _dr_subprocess import _launch_general_merge_resolver_process

    redis_client = MagicMock()
    captured = {}

    def _fake_run(**kwargs):
        captured["env"] = kwargs["env"]
        return {"success": True, "message": "ok", "output": ""}

    with patch("_dr_subprocess._run_subprocess_streaming", side_effect=_fake_run):
        _launch_general_merge_resolver_process(
            "runner-general",
            "impl/fix-branch",
            "very long error message",
            redis_client,
        )

    env = captured["env"]
    plan_keys = {k for k in env if k.startswith("PLAN_RUNNER_")}
    assert plan_keys == {
        "PLAN_RUNNER_RUNNER_ID",
        "PLAN_RUNNER_PROJECT_ROOT",
        "PLAN_RUNNER_WORK_DIR",
        "PLAN_RUNNER_MERGE_ERROR",
    }
    assert env["PLAN_RUNNER_MERGE_ERROR"] == "very long error message"
    assert "PLAN_RUNNER_BRANCH" not in env
    assert "PLAN_RUNNER_WORKTREE_PATH" not in env
