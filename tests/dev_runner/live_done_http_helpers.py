"""live /plans/{path}/done HTTP 테스트용 격리 project helper."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = REPO_ROOT / ".tmp" / "live_done_http"


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stdout}\n{result.stderr}")


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    except OSError:
        pass


def _rmtree_onerror(func, path, exc_info) -> None:
    _make_writable(path)
    func(path)


def _rmtree_onexc(func, path, exc) -> None:
    _make_writable(path)
    func(path)


def _remove_tree_or_raise(path: Path, attempts: int = 5) -> None:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        if not path.exists():
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_rmtree_onexc)
            else:
                shutil.rmtree(path, onerror=_rmtree_onerror)
        except BaseException as exc:
            last_error = exc
        if not path.exists():
            return
        time.sleep(0.1 * (attempt + 1))
    if path.exists():
        raise RuntimeError(f"isolated live done project cleanup failed: {path}") from last_error


@dataclass
class LiveDoneProject:
    root: Path
    plans_dir: Path
    archive_dir: Path
    todo_path: Path
    done_path: Path

    def write_plan(
        self,
        *,
        filename: str,
        title: str,
        status: str,
        body: str,
        todo_entry: str | None = None,
        subdir: str = "docs/plan",
    ) -> Path:
        target_dir = self.root / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        plan_path = target_dir / filename
        plan_path.write_text(
            f"# {title}\n"
            f"> 상태: {status}\n"
            "> 진행률: 2/2 (100%)\n"
            "\n"
            f"{body}",
            encoding="utf-8",
        )
        if todo_entry:
            todo_text = self.todo_path.read_text(encoding="utf-8")
            if todo_entry not in todo_text:
                self.todo_path.write_text(todo_text + todo_entry, encoding="utf-8")
        return plan_path


@contextmanager
def isolated_live_done_project(prefix: str):
    """허용 루트 내부에 nested git repo를 가진 임시 project를 만든다."""
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    project_root = Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=str(TMP_ROOT)))

    docs_dir = project_root / "docs"
    plans_dir = docs_dir / "plan"
    archive_dir = docs_dir / "archive"
    plans_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    plans_root = project_root / ".worktrees" / "plans"
    plans_docs_dir = plans_root / "docs"
    plans_docs_dir.mkdir(parents=True, exist_ok=True)
    todo_path = plans_root / "TODO.md"
    done_path = plans_docs_dir / "DONE.md"
    todo_path.write_text("# TODO\n\n## In Progress\n\n## Pending\n", encoding="utf-8")
    done_path.write_text("# DONE (최근 20개)\n\n", encoding="utf-8")
    (project_root / "README.md").write_text("temp live done http test project\n", encoding="utf-8")

    _run_git(["init"], project_root)
    _run_git(["config", "user.name", "Codex Test"], project_root)
    _run_git(["config", "user.email", "codex-test@example.com"], project_root)
    _run_git(["add", "README.md", ".worktrees/plans/TODO.md", ".worktrees/plans/docs/DONE.md"], project_root)
    _run_git(["commit", "-m", "test: seed isolated live done project"], project_root)

    try:
        yield LiveDoneProject(
            root=project_root,
            plans_dir=plans_dir,
            archive_dir=archive_dir,
            todo_path=todo_path,
            done_path=done_path,
        )
    finally:
        _remove_tree_or_raise(project_root)
