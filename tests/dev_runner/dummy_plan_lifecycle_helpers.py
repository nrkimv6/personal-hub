from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DUMMY_PLAN_FIXTURE = "test_playwright_dummy_plan.md"
DUMMY_PLAN_SENTINEL = "DUMMY_PLAN_PLAYWRIGHT_SENTINEL"
RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"
COMMANDS_KEY = "plan-runner:commands"

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "dummy-plan-test",
    "GIT_AUTHOR_EMAIL": "dummy-plan-test@example.invalid",
    "GIT_COMMITTER_NAME": "dummy-plan-test",
    "GIT_COMMITTER_EMAIL": "dummy-plan-test@example.invalid",
}


@dataclass(frozen=True)
class DummyTempRepo:
    repo_root: Path
    worktree_base: Path
    branch: str
    worktree_path: Path
    marker_relpath: str
    marker_text: str


@dataclass(frozen=True)
class DummyRunnerArtifacts:
    runner_id: str
    plan_file: Path
    stream_log_path: Path
    log_file_path: Path
    worktree_path: Path | None = None
    branch: str | None = None


def normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def init_dummy_temp_repo(tmp_path: Path, *, runner_id: str = "t-dummy-plan-lifecycle") -> DummyTempRepo:
    repo_root = tmp_path / "dummy-repo"
    repo_root.mkdir()
    _run_git(repo_root, "init", "-b", "main")
    _run_git(repo_root, "config", "commit.gpgsign", "false")
    _run_git(repo_root, "config", "user.name", "dummy-plan-test")
    _run_git(repo_root, "config", "user.email", "dummy-plan-test@example.invalid")

    (repo_root / "README.md").write_text("dummy temp repo\n", encoding="utf-8")
    _run_git(repo_root, "add", "README.md")
    _run_git(repo_root, "commit", "-m", "init")

    worktree_base = repo_root / ".worktrees"
    worktree_base.mkdir()
    branch = f"runner/{runner_id}"
    worktree_path = worktree_base / runner_id
    _run_git(repo_root, "worktree", "add", str(worktree_path), "-b", branch)

    marker_relpath = "dummy-plan-playwright-marker.txt"
    marker_text = f"{DUMMY_PLAN_SENTINEL}\n"
    (worktree_path / marker_relpath).write_text(marker_text, encoding="utf-8")
    _run_git(worktree_path, "add", marker_relpath)
    _run_git(worktree_path, "commit", "-m", "test: dummy plan marker")
    _run_git(repo_root, "checkout", "main")

    return DummyTempRepo(
        repo_root=repo_root,
        worktree_base=worktree_base,
        branch=branch,
        worktree_path=worktree_path,
        marker_relpath=marker_relpath,
        marker_text=marker_text,
    )


def seed_dummy_runner_state(
    redis_client,
    *,
    runner_id: str,
    plan_file: Path,
    tmp_path: Path,
    status: str = "running",
    stream_lines: Iterable[str] | None = None,
    repo: DummyTempRepo | None = None,
) -> DummyRunnerArtifacts:
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream_log = log_dir / f"plan-runner-stream-{runner_id}.log"
    main_log = log_dir / f"plan-runner-{runner_id}.log"
    lines = list(stream_lines or [f"[INFO] {DUMMY_PLAN_SENTINEL}"])
    content = "\n".join(lines).rstrip() + "\n"
    stream_log.write_text(content, encoding="utf-8")
    main_log.write_text(content, encoding="utf-8")

    prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}"
    redis_client.sadd(ACTIVE_RUNNERS_KEY, runner_id)
    redis_client.zadd(RECENT_RUNNERS_KEY, {runner_id: datetime.now(timezone.utc).timestamp()})
    values = {
        "status": status,
        "pid": str(os.getpid()),
        "plan_file": str(plan_file),
        "engine": "codex",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "current_cycle": "1",
        "execution_count": "1",
        "stream_log_path": str(stream_log),
        "log_file_path": str(main_log),
        "trigger": "tc:dummy_plan_playwright",
        "test_source": "dummy_plan_playwright",
    }
    if repo is not None:
        values.update(
            {
                "worktree_path": str(repo.worktree_path),
                "branch": repo.branch,
            }
        )
    for suffix, value in values.items():
        redis_client.set(f"{prefix}:{suffix}", value)

    return DummyRunnerArtifacts(
        runner_id=runner_id,
        plan_file=plan_file,
        stream_log_path=stream_log,
        log_file_path=main_log,
        worktree_path=repo.worktree_path if repo else None,
        branch=repo.branch if repo else None,
    )


def cleanup_dummy_runner_state(redis_client, runner_id: str, *, temp_root: Path | None = None) -> None:
    prefix = f"{RUNNER_KEY_PREFIX}:{runner_id}:"
    for key in list(redis_client.scan_iter(f"{prefix}*")):
        redis_client.delete(key)
    redis_client.srem(ACTIVE_RUNNERS_KEY, runner_id)
    redis_client.zrem(RECENT_RUNNERS_KEY, runner_id)
    redis_client.delete(f"plan-runner:recent-meta:{runner_id}")
    redis_client.delete(f"plan-runner:logs:list:{runner_id}")

    if temp_root is not None:
        root = temp_root.resolve(strict=False)
        repo = temp_root / "dummy-repo"
        worktree_dir = repo / ".worktrees" / runner_id
        if repo.exists():
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_dir), "--force"],
                cwd=str(repo),
                env=_GIT_ENV,
                capture_output=True,
                text=True,
                timeout=15,
            )
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(repo),
                env=_GIT_ENV,
                capture_output=True,
                text=True,
                timeout=15,
            )
            subprocess.run(
                ["git", "branch", "-D", f"runner/{runner_id}"],
                cwd=str(repo),
                env=_GIT_ENV,
                capture_output=True,
                text=True,
                timeout=15,
            )
        for candidate in (repo / ".worktrees").glob("*"):
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)


def add_plan_runner_scripts_to_path() -> Path:
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return scripts_dir
