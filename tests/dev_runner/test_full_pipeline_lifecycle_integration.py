from __future__ import annotations

import importlib.util
import json
import subprocess
import textwrap
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.modules.dev_runner.schemas import RunRequest
from app.modules.dev_runner.services.executor_service import executor_service
from tests.dev_runner._path_helpers import get_listener_script_path, get_repo_root
from tests.dev_runner.conftest_e2e import HEARTBEAT_KEY, isolated_redis_db15
from tests.dev_runner.dummy_plan_lifecycle_helpers import (
    COMMANDS_KEY,
    DUMMY_PLAN_SENTINEL,
    FullLifecycleContext,
    assert_full_lifecycle_clean,
    init_full_lifecycle_repo,
)


pytestmark = pytest.mark.http


def _load_listener_module():
    scripts_dir = Path(get_listener_script_path()).parent
    import sys

    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    sys.modules["listener_noise_filter"] = types.ModuleType("listener_noise_filter")
    sys.modules["listener_noise_filter"].NOISE_BLOCK_MARKERS = []
    sys.modules["listener_noise_filter"].is_noise_line = lambda line: False
    spec = importlib.util.spec_from_file_location("_listener_full_lifecycle", get_listener_script_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_scripted_engine(tmp_path: Path) -> Path:
    script = tmp_path / "scripted_engine.py"
    script.write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations

            import argparse
            import os
            import re
            import subprocess
            from pathlib import Path

            import redis

            parser = argparse.ArgumentParser()
            parser.add_argument("--plan-file", required=True)
            parser.add_argument("--runner-id", required=True)
            args = parser.parse_args()

            worktree = Path(os.environ["PLAN_RUNNER_WORKTREE_PATH"])
            plan_file = Path(args.plan_file)
            marker_rel = os.environ.get("DEV_RUNNER_TEST_MARKER_RELPATH", "full-lifecycle-marker.txt")
            marker = worktree / marker_rel
            marker.write_text("{DUMMY_PLAN_SENTINEL}\\n", encoding="utf-8")

            text = plan_file.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"\\[ \\]", "[x]", text)
            text = re.sub(r"(>\\s*상태:\\s*).+", r"\\1머지대기", text)
            text = re.sub(r"(>\\s*진행률:\\s*).+", r"\\g<1>1/1 (100%)", text)
            text = re.sub(r"\\*상태:.*?\\| 진행률:.*?\\*", "*상태: 머지대기 | 진행률: 1/1 (100%)*", text)
            plan_file.write_text(text, encoding="utf-8")

            env = os.environ.copy()
            env.update({{
                "GIT_AUTHOR_NAME": "scripted-engine",
                "GIT_AUTHOR_EMAIL": "scripted-engine@example.invalid",
                "GIT_COMMITTER_NAME": "scripted-engine",
                "GIT_COMMITTER_EMAIL": "scripted-engine@example.invalid",
            }})
            subprocess.run(["git", "add", marker_rel, str(plan_file.relative_to(worktree))], cwd=str(worktree), env=env, check=True)
            subprocess.run(["git", "commit", "-m", "test: scripted full lifecycle"], cwd=str(worktree), env=env, check=True)

            r = redis.Redis(host="localhost", port=6379, db=int(os.environ.get("REDIS_DB", "15")), decode_responses=True)
            r.set(f"plan-runner:runners:{{args.runner_id}}:merge_requested", "1")
            r.set(f"plan-runner:runners:{{args.runner_id}}:exit_reason", "completed")
            print("scripted engine completed")
            """
        ),
        encoding="utf-8",
    )
    return script


def _wait_until(predicate, *, timeout: float = 45.0, interval: float = 0.25) -> None:
    deadline = time.time() + timeout
    last_error: AssertionError | None = None
    while time.time() < deadline:
        try:
            if predicate():
                return
        except AssertionError as exc:
            last_error = exc
        time.sleep(interval)
    if last_error:
        raise last_error
    raise AssertionError("condition not reached before timeout")


def _worktree_absent(repo_root: Path, runner_worktree: Path) -> bool:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=15,
    )
    return str(runner_worktree).replace("\\", "/") not in result.stdout.replace("\\", "/")


def _branch_absent(repo_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip() == ""


@pytest.mark.asyncio
async def test_full_pipeline_start_to_archive_cleanup_readback(isolated_redis_db15, tmp_path, monkeypatch):
    repo_root, plan_path = init_full_lifecycle_repo(tmp_path)
    scripted_engine = _write_scripted_engine(tmp_path)
    isolated_redis_db15.flushdb()
    isolated_redis_db15.set(HEARTBEAT_KEY, "alive")

    monkeypatch.setenv("PLAN_RUNNER_REDIS_DB", "15")
    monkeypatch.setenv("DEV_RUNNER_ALLOW_TEST_REPO_ROOT", "1")
    monkeypatch.setenv("DEV_RUNNER_TEST_ENGINE_SCRIPT", str(scripted_engine))
    monkeypatch.delenv("DEV_RUNNER_TEST_IN_PROCESS_DONE", raising=False)
    monkeypatch.setenv("DEV_RUNNER_TEST_MARKER_RELPATH", "full-lifecycle-marker.txt")
    monkeypatch.setenv("MERGE_TEST_LOCK_TIMEOUT", "20")
    executor_service.reconnect()

    settings = SimpleNamespace(max_concurrent_runners=3, default_engine="codex", default_fix_engine="codex")
    with patch("app.modules.dev_runner.services.executor_service.settings_service.get", return_value=settings):
        response = await executor_service.start_dev_runner(
            RunRequest(
                plan_file=str(plan_path),
                engine="codex",
                fix_engine="codex",
                test_source="full_pipeline_lifecycle",
                test_repo_root=str(repo_root),
                worktree=True,
                dry_run=False,
            )
        )

    command_item = isolated_redis_db15.brpop(COMMANDS_KEY, timeout=5)
    assert command_item is not None
    _, raw_command = command_item
    command = json.loads(raw_command)
    assert command["test_source"] == "full_pipeline_lifecycle"
    assert command["test_repo_root"] == str(repo_root)

    listener = _load_listener_module()
    import _dr_constants

    _dr_constants.set_redis_db(15)
    listener.execute_command(command, isolated_redis_db15)

    runner_id = response.runner_id
    runner_branch = f"runner/{runner_id}"
    runner_worktree = repo_root / ".worktrees" / runner_id
    archive_path = repo_root / "docs" / "archive" / plan_path.name
    marker_path = repo_root / "full-lifecycle-marker.txt"

    def lifecycle_finished() -> bool:
        return (
            archive_path.exists()
            and _worktree_absent(repo_root, runner_worktree)
            and _branch_absent(repo_root, runner_branch)
        )

    _wait_until(lifecycle_finished, timeout=60)

    ctx = FullLifecycleContext(
        repo_root=repo_root,
        runner_id=runner_id,
        runner_branch=runner_branch,
        runner_worktree=runner_worktree,
        original_plan_path=plan_path,
        archive_plan_path=archive_path,
        marker_path=marker_path,
        redis_client=isolated_redis_db15,
        monitor_root_marker_path=Path(get_repo_root()) / "full-lifecycle-marker.txt",
    )
    assert_full_lifecycle_clean(ctx)

    assert isolated_redis_db15.get(f"plan-runner:runners:{runner_id}:done_post_merge_status") in (None, "success")
