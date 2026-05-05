"""Helpers for committing files that may belong to multiple git roots."""

import asyncio
import subprocess
from pathlib import Path
from typing import Callable, Iterable


def _resolve_git_root(path: Path, default_root: Path | None = None) -> Path | None:
    """Return the git root for a file path, falling back to default_root."""
    cwd = path if path.is_dir() else path.parent
    while not cwd.exists() and cwd != cwd.parent:
        cwd = cwd.parent
    if cwd.exists():
        try:
            result = subprocess.run(
                ["git", "-c", "safe.directory=*", "rev-parse", "--show-toplevel"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip()).resolve()
        except Exception:
            pass
    return default_root.resolve() if default_root and default_root.exists() else None


def _git_pathspec(path: Path, git_root: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(git_root.resolve()))
    except ValueError:
        if path.exists():
            return str(path)
    return None


def _is_tracked(git_root: Path, pathspec: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", "ls-files", "--error-unmatch", "--", pathspec],
            cwd=str(git_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _stageable_pathspecs(git_root: Path, files: Iterable[Path]) -> list[str]:
    """Return safe git-add pathspecs for existing files and tracked deletions."""
    pathspecs: list[str] = []
    seen: set[str] = set()
    for file_path in files:
        path = Path(file_path)
        pathspec = _git_pathspec(path, git_root)
        if pathspec is None:
            continue
        if not path.exists() and not _is_tracked(git_root, pathspec):
            continue
        if pathspec not in seen:
            pathspecs.append(pathspec)
            seen.add(pathspec)
    return pathspecs


def group_files_by_git_root(
    files: Iterable[Path],
    default_root: Path | None = None,
) -> dict[Path, list[Path]]:
    """Group file paths by the git worktree that owns them."""
    groups: dict[Path, list[Path]] = {}
    for file_path in files:
        root = _resolve_git_root(Path(file_path), default_root)
        if root is None:
            continue
        groups.setdefault(root, []).append(Path(file_path))
    return groups


def _has_staged_changes(git_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", "diff", "--cached", "--quiet"],
        cwd=str(git_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    return result.returncode == 1


async def commit_files_by_git_root(
    *,
    files_to_add: list[Path],
    default_root: Path | None,
    commit_command: list[str],
    decode_output: Callable[[object], str],
    commit_timeout: int = 60,
) -> str:
    """Stage and commit files in the git root that owns each file.

    Plan documents and TODO/DONE ledgers can live in `.worktrees/plans`
    while implementation files live in the project root. Running one
    `git add` from the project root cannot reliably stage both.
    """
    all_files = [Path(f) for f in files_to_add]
    if not all_files:
        return "커밋할 파일 없음"

    groups = group_files_by_git_root(all_files, default_root)
    if not groups:
        return "커밋할 파일 없음"

    outputs: list[str] = []
    for git_root, files in groups.items():
        pathspecs = _stageable_pathspecs(git_root, files)
        if pathspecs:
            add_proc = await asyncio.create_subprocess_exec(
                "git",
                "-c",
                "safe.directory=*",
                "add",
                "--",
                *pathspecs,
                cwd=str(git_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            add_stdout, _ = await add_proc.communicate()
            if add_proc.returncode != 0:
                output = decode_output(add_stdout)
                raise RuntimeError(f"git add failed ({add_proc.returncode}): {output}".strip())

        if not _has_staged_changes(git_root):
            outputs.append(f"{git_root}: 커밋할 staged 변경 없음")
            continue

        commit_proc = await asyncio.create_subprocess_exec(
            *commit_command,
            cwd=str(git_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(commit_proc.communicate(), timeout=commit_timeout)
        output = decode_output(stdout)
        if commit_proc.returncode != 0:
            raise RuntimeError(f"commit script failed ({commit_proc.returncode}): {output}".strip())
        outputs.append(output)

    return "\n".join(o for o in outputs if o).strip() or "커밋할 staged 변경 없음"
