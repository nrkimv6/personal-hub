from __future__ import annotations

import os
import re
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


@dataclass(frozen=True)
class FullLifecycleContext:
    repo_root: Path
    runner_id: str
    runner_branch: str
    runner_worktree: Path
    original_plan_path: Path
    archive_plan_path: Path
    marker_path: Path
    redis_client: object | None = None
    http_response: dict | None = None
    logs_full_response: dict | None = None
    monitor_root_marker_path: Path | None = None


@dataclass(frozen=True)
class ConflictLifecycleContext(FullLifecycleContext):
    conflict_file_path: Path | None = None
    expected_resolved_content: str = "RESOLVED_VERSION\n"


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


def init_full_lifecycle_repo(tmp_path: Path, *, plan_name: str = "2026-05-22_test-full-pipeline-plan.md") -> tuple[Path, Path]:
    repo_root = tmp_path / "full-lifecycle-repo"
    repo_root.mkdir()
    _run_git(repo_root, "init", "-b", "main")
    _run_git(repo_root, "config", "commit.gpgsign", "false")
    _run_git(repo_root, "config", "user.name", "dummy-plan-test")
    _run_git(repo_root, "config", "user.email", "dummy-plan-test@example.invalid")

    plan_path = repo_root / "docs" / "plan" / plan_name
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        "\n".join(
            [
                "# test full pipeline plan",
                "",
                "> 상태: 구현중",
                "> 진행률: 0/1 (0%)",
                "",
                "## TODO",
                "- [ ] create lifecycle marker",
                "",
                "*상태: 구현중 | 진행률: 0/1 (0%)*",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (repo_root / "README.md").write_text("full lifecycle repo\n", encoding="utf-8")
    _run_git(repo_root, "add", "README.md", str(plan_path.relative_to(repo_root)))
    _run_git(repo_root, "commit", "-m", "init full lifecycle plan")
    return repo_root, plan_path


def init_conflict_lifecycle_repo(
    tmp_path: Path,
    *,
    runner_id: str = "t-conflict-lifecycle",
    plan_name: str = "2026-05-22_test-conflict-plan.md",
) -> ConflictLifecycleContext:
    repo_root, plan_path = init_full_lifecycle_repo(tmp_path, plan_name=plan_name)
    conflict_file = repo_root / "conflict_target.txt"
    conflict_file.write_text("BASELINE\n", encoding="utf-8")
    _run_git(repo_root, "add", "conflict_target.txt")
    _run_git(repo_root, "commit", "-m", "init conflict target")

    branch = f"runner/{runner_id}"
    worktree = repo_root / ".worktrees" / runner_id
    _run_git(repo_root, "worktree", "add", str(worktree), "-b", branch)

    conflict_file.write_text("MAIN_VERSION\n", encoding="utf-8")
    _run_git(repo_root, "add", "conflict_target.txt")
    _run_git(repo_root, "commit", "-m", "main conflict side")

    (worktree / "conflict_target.txt").write_text("RUNNER_VERSION\n", encoding="utf-8")
    marker_path = worktree / "full-lifecycle-marker.txt"
    marker_path.write_text(f"{DUMMY_PLAN_SENTINEL}\n", encoding="utf-8")
    worktree_plan = worktree / "docs" / "plan" / plan_name
    text = worktree_plan.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\[ \]", "[x]", text)
    text = re.sub(r"(>\s*상태:\s*).+", r"\1머지대기", text)
    text = re.sub(r"(>\s*진행률:\s*).+", r"\g<1>1/1 (100%)", text)
    text = re.sub(r"\*상태:.*?\| 진행률:.*?\*", "*상태: 머지대기 | 진행률: 1/1 (100%)*", text)
    worktree_plan.write_text(text, encoding="utf-8")
    _run_git(worktree, "add", "conflict_target.txt", "full-lifecycle-marker.txt", str(worktree_plan.relative_to(worktree)))
    _run_git(worktree, "commit", "-m", "runner conflict side")

    return ConflictLifecycleContext(
        repo_root=repo_root,
        runner_id=runner_id,
        runner_branch=branch,
        runner_worktree=worktree,
        original_plan_path=plan_path,
        archive_plan_path=repo_root / "docs" / "archive" / plan_name,
        marker_path=repo_root / "full-lifecycle-marker.txt",
        conflict_file_path=conflict_file,
    )


def _git_stdout(repo: Path, *args: str) -> str:
    return _run_git(repo, *args).stdout


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_full_lifecycle_clean(ctx: FullLifecycleContext) -> None:
    _assert(ctx.marker_path.exists(), f"marker missing: {ctx.marker_path}")
    marker_text = ctx.marker_path.read_text(encoding="utf-8", errors="replace")
    _assert(DUMMY_PLAN_SENTINEL in marker_text, f"marker mismatch: {ctx.marker_path}")

    _assert(not ctx.original_plan_path.exists(), f"active plan residue: {ctx.original_plan_path}")
    _assert(ctx.archive_plan_path.exists(), f"archive missing: {ctx.archive_plan_path}")

    archive_text = ctx.archive_plan_path.read_text(encoding="utf-8", errors="replace")
    _assert(re.search(r">\s*상태:\s*(구현완료|완료)", archive_text), "archive status not completed")
    _assert(re.search(r">\s*완료일:\s*\d{4}-\d{2}-\d{2}", archive_text), "archive completion date missing")
    _assert("[ ]" not in archive_text, "archive has unchecked TODO")
    if "진행률" in archive_text:
        _assert("100%" in archive_text, "archive progress is not 100%")

    worktrees = _git_stdout(ctx.repo_root, "worktree", "list", "--porcelain").replace("\\", "/")
    _assert(normalize_path(ctx.runner_worktree) not in worktrees, f"worktree residue: {ctx.runner_worktree}")
    branches = _git_stdout(ctx.repo_root, "branch", "--list", ctx.runner_branch)
    _assert(branches.strip() == "", f"branch residue: {ctx.runner_branch}")

    if ctx.monitor_root_marker_path is not None:
        _assert(not ctx.monitor_root_marker_path.exists(), f"monitor root marker residue: {ctx.monitor_root_marker_path}")


def assert_full_lifecycle_preserved(ctx: FullLifecycleContext) -> None:
    _assert(ctx.original_plan_path.exists(), f"active plan missing: {ctx.original_plan_path}")
    _assert(not ctx.archive_plan_path.exists(), f"archive unexpectedly exists: {ctx.archive_plan_path}")
    worktrees = _git_stdout(ctx.repo_root, "worktree", "list", "--porcelain").replace("\\", "/")
    _assert(normalize_path(ctx.runner_worktree) in worktrees, f"worktree not preserved: {ctx.runner_worktree}")
    branches = _git_stdout(ctx.repo_root, "branch", "--list", ctx.runner_branch)
    _assert(ctx.runner_branch in branches, f"branch not preserved: {ctx.runner_branch}")


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
