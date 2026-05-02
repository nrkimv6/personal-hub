"""Shared runtime helpers for browser worker management."""

import os
import sys
import time
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ORIGINAL_CWD = Path.cwd().resolve()
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


class RepoCheckoutError(RuntimeError):
    """Raised when a service command is launched from a non-root checkout."""


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _allowed_root_checkout(project_root: Path) -> Path:
    git_entry = project_root / ".git"
    if not git_entry.is_file():
        return project_root

    try:
        content = git_entry.read_text(encoding="utf-8").strip()
    except OSError:
        return project_root

    prefix = "gitdir:"
    if not content.lower().startswith(prefix):
        return project_root

    git_dir = Path(content[len(prefix):].strip())
    if not git_dir.is_absolute():
        git_dir = (project_root / git_dir).resolve()

    if git_dir.parent.name == "worktrees" and git_dir.parent.parent.name == ".git":
        return git_dir.parent.parent.parent
    return project_root


def assert_repo_root_checkout(
    *,
    project_root: Path = PROJECT_ROOT,
    cwd: Path = ORIGINAL_CWD,
) -> None:
    """Allow service operations only from the canonical root checkout.

    Linked worktrees have a file-shaped .git entry. Root scripts launched while
    the shell is inside .worktrees/* are also rejected because operational
    service commands must always be run from the root checkout.
    """
    project_root = project_root.resolve()
    cwd = cwd.resolve()
    git_entry = project_root / ".git"
    worktrees_dir = project_root / ".worktrees"

    if git_entry.is_file() or (worktrees_dir.exists() and _is_under(cwd, worktrees_dir)):
        allowed_root = _allowed_root_checkout(project_root)
        raise RepoCheckoutError(
            "service commands must be run from the root checkout only; "
            f"current checkout={cwd}; allowed root checkout={allowed_root}"
        )


def cprint(msg: str, color: str = RESET):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{GRAY}[{ts}]{RESET} {color}{msg}{RESET}")


def _kill_by_cmdline(pattern: str) -> int:
    """Terminate processes whose cmdline contains pattern.

    Returns the number of processes killed. Self and all ancestor processes
    are excluded to avoid killing the running CLI context.
    """
    self_pid = os.getpid()
    excluded_pids = {self_pid}
    try:
        for parent in psutil.Process(self_pid).parents():
            excluded_pids.add(parent.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    killed = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.pid in excluded_pids:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(pattern in arg for arg in cmdline):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed
