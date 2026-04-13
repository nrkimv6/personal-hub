"""워크트리 목록 및 커밋 정보 조회 서비스"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from app.modules.dev_runner.schemas import (
    BranchUnresolvedPlan,
    CommitDiffStat,
    MainDirtyStatus,
    PlanOnlyBranch,
    WorktreeCommit,
    WorktreeInfo,
    WorktreeListResponse,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # monitor-page 루트


async def _run_git(*args: str, repo_root: Path = _REPO_ROOT) -> str:
    """git 명령 실행 헬퍼 — 실패 시 빈 문자열 반환.

    `-c safe.directory=*`를 자동 주입하여 NSSM SYSTEM 계정에서 실행 시
    git 2.35.2+의 dubious ownership 에러를 방지한다.

    ⚠️ 중복 주의: scripts/worktree_manager.py:_run_git에도 동일한 safe.directory
    주입 로직이 있다. 하나를 수정할 때 반드시 다른 쪽도 함께 확인할 것.
    """
    if not repo_root.exists() or not repo_root.is_dir():
        return ""

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-c", "safe.directory=*", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(repo_root),
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return ""
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


async def list_worktrees(repo_root: Path = _REPO_ROOT) -> list[dict]:
    """git worktree list --porcelain 파싱 → 브랜치명 == main 제외, detached HEAD 제외"""
    output = await _run_git("worktree", "list", "--porcelain", repo_root=repo_root)
    if not output:
        return []

    result = []
    block: dict = {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if block:
                _maybe_append(block, result)
            block = {"worktree_path": line[len("worktree "):].strip(), "locked": False}
        elif line.startswith("HEAD "):
            block["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            raw = line[len("branch "):].strip()
            block["branch"] = raw.removeprefix("refs/heads/")
        elif line == "detached":
            block["detached"] = True
        elif line.startswith("locked"):
            block["locked"] = True

    if block:
        _maybe_append(block, result)

    return result


def _maybe_append(block: dict, result: list) -> None:
    """detached HEAD 및 branch == main 제외"""
    if block.get("detached"):
        return
    branch = block.get("branch", "")
    if branch == "main":
        return
    result.append(block)


def _format_plan_mtime(plan_file: Path) -> Optional[str]:
    """계획서 mtime -> ISO 문자열 변환."""
    try:
        return datetime.fromtimestamp(plan_file.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def _read_plan_header_branch(top_lines: Sequence[str]) -> Optional[str]:
    """상위 20줄에서 > branch: 헤더 반환."""
    pattern = re.compile(r"^>\s*branch:\s*(.+)\s*$")
    for line in top_lines:
        match = pattern.match(line.rstrip())
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


async def get_ahead_behind(branch: str, repo_root: Path = _REPO_ROOT) -> tuple[int, int]:
    """main 대비 ahead/behind 커밋 수 반환"""
    ahead_str, behind_str = await asyncio.gather(
        _run_git("rev-list", "--count", f"main..{branch}", repo_root=repo_root),
        _run_git("rev-list", "--count", f"{branch}..main", repo_root=repo_root),
    )
    try:
        ahead = int(ahead_str) if ahead_str else 0
    except ValueError:
        ahead = 0
    try:
        behind = int(behind_str) if behind_str else 0
    except ValueError:
        behind = 0
    return ahead, behind


async def get_worktree_commits(branch: str, repo_root: Path = _REPO_ROOT) -> list[WorktreeCommit]:
    """main 이후 커밋 목록 + 각 커밋의 diff stat 반환 (빈 브랜치 방어)"""
    log_output = await _run_git(
        "log", f"main..{branch}",
        "--format=%H|%ai|%s",
        repo_root=repo_root,
    )
    if not log_output:
        return []

    commits = []
    hashes = []
    raw_commits = []
    for line in log_output.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        full_hash, date_str, message = parts
        hashes.append(full_hash)
        raw_commits.append((full_hash, date_str, message))

    # diff stat 병렬 조회
    diff_tasks = [
        _run_git("diff-tree", "--no-commit-id", "-r", "--numstat", h)
        for h in hashes
    ]
    diff_outputs = await asyncio.gather(*diff_tasks)

    for (full_hash, date_str, message), diff_output in zip(raw_commits, diff_outputs):
        diff_stat = _parse_numstat(diff_output)
        commits.append(WorktreeCommit(
            hash=full_hash,
            short_hash=full_hash[:7],
            message=message,
            date=date_str,
            diff_stat=diff_stat,
        ))

    return commits


def _parse_numstat(output: str) -> list[CommitDiffStat]:
    """git diff-tree --numstat 출력 파싱 (탭 구분: added\\tdeleted\\tpath)"""
    stats = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        added_str, deleted_str, path = parts
        try:
            added = int(added_str)
            deleted = int(deleted_str)
            changes = f"+{added} -{deleted}"
        except ValueError:
            # 바이너리 파일은 '-' 로 표시됨
            changes = f"{added_str} {deleted_str}"
        stats.append(CommitDiffStat(file=path, changes=changes))
    return stats


def _iter_dirty_paths_from_porcelain_z(status_output: str) -> list[str]:
    """`git status --porcelain=v1 -z` 결과에서 최종 dirty 파일 경로 추출."""
    tokens = status_output.split("\0")
    files: list[str] = []
    i = 0

    while i < len(tokens):
        token = tokens[i]
        if not token:
            i += 1
            continue

        if len(token) < 4 or token[2] != " ":
            i += 1
            continue

        status = token[:2]
        path = token[3:]

        if status in {"R ", "C "} and i + 1 < len(tokens):
            # rename/copy: token[0]가 source path, 다음 토큰이 destination path
            i += 1
            path = tokens[i]

        if path:
            files.append(path)

        i += 1

    return files


def find_plan_file(branch: str, repo_root: Path = _REPO_ROOT) -> tuple[Optional[str], Optional[str]]:
    """docs/plan/*.md 에서 > branch: {branch} 헤더를 찾아 경로 반환 (sync)

    기존 plan_scanner/plan_path_resolver에 유사 로직 없으므로 자체 구현.
    """
    plan_dir = repo_root / "docs" / "plan"
    if not plan_dir.exists():
        return None, None

    pattern = re.compile(rf"^>\s*branch:\s*{re.escape(branch)}\s*$")
    for md_file in plan_dir.glob("*.md"):
        try:
            with open(md_file, encoding="utf-8") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    lines.append(line)
                if any(pattern.match(line.rstrip()) for line in lines):
                    return str(md_file.relative_to(repo_root)), _format_plan_mtime(md_file)
        except (OSError, UnicodeDecodeError):
            continue
    return None, None


def list_plan_only_branches(
    existing_branches: set[str],
    repo_root: Path = _REPO_ROOT,
) -> tuple[list[PlanOnlyBranch], list[BranchUnresolvedPlan]]:
    """`docs/plan` 스캔 결과로 active 되지 않은 plan-only/branch 미매칭을 계산"""
    plan_dir = repo_root / "docs" / "plan"
    if not plan_dir.exists():
        return [], []

    plan_only: list[PlanOnlyBranch] = []
    branch_unresolved: list[BranchUnresolvedPlan] = []

    for md_file in plan_dir.glob("*.md"):
        try:
            with open(md_file, encoding="utf-8") as f:
                top_lines: list[str] = []
                for idx, line in enumerate(f):
                    if idx >= 20:
                        break
                    top_lines.append(line)
        except (OSError, UnicodeDecodeError):
            continue

        branch = _read_plan_header_branch(top_lines)
        relative_path = md_file.relative_to(repo_root)
        plan_mtime = _format_plan_mtime(md_file)
        if not branch:
            branch_unresolved.append(
            BranchUnresolvedPlan(
                plan_file=str(relative_path),
                reason="missing > branch header",
                plan_mtime=plan_mtime,
            )
            )
            continue

        if branch not in existing_branches:
            plan_only.append(
                PlanOnlyBranch(
                    plan_file=str(relative_path),
                    branch=branch,
                    plan_mtime=plan_mtime,
                )
            )

    return plan_only, branch_unresolved


async def get_main_dirty(repo_root: Path = _REPO_ROOT) -> MainDirtyStatus:
    """main 브랜치 작업트리 기준 dirty 파일 목록."""
    status_output = await _run_git("status", "--porcelain=v1", "-z", repo_root=repo_root)
    if not status_output:
        return MainDirtyStatus()

    files = _iter_dirty_paths_from_porcelain_z(status_output)

    unique_files = []
    seen: set[str] = set()
    for item in files:
        if item in seen:
            continue
        seen.add(item)
        unique_files.append(item)

    return MainDirtyStatus(dirty_count=len(unique_files), files=unique_files)


async def get_all_worktrees(repo_root: Path = _REPO_ROOT) -> WorktreeListResponse:
    """전체 워크트리 + plan-only + 미해결 plan + main dirty 통합 응답."""
    raw_worktrees = await list_worktrees(repo_root=repo_root)
    existing_branches = {wt["branch"] for wt in raw_worktrees if wt.get("branch")}

    async def _build(wt: dict) -> WorktreeInfo:
        branch = wt["branch"]
        (ahead, behind), commits, plan_match = await asyncio.gather(
            get_ahead_behind(branch, repo_root=repo_root),
            get_worktree_commits(branch, repo_root=repo_root),
            asyncio.to_thread(find_plan_file, branch, repo_root),
        )
        plan_file, plan_mtime = plan_match
        created_at = commits[-1].date if commits else None
        return WorktreeInfo(
            branch=branch,
            worktree_path=wt["worktree_path"],
            created_at=created_at,
            ahead=ahead,
            behind=behind,
            locked=wt.get("locked", False),
            commits=commits,
            plan_file=plan_file,
            plan_mtime=plan_mtime,
        )

    plan_only, branch_unresolved = await asyncio.to_thread(list_plan_only_branches, existing_branches, repo_root)
    worktrees = await asyncio.gather(*[_build(wt) for wt in raw_worktrees]) if raw_worktrees else []
    main_dirty = await get_main_dirty(repo_root=repo_root)

    return WorktreeListResponse(
        worktrees=list(worktrees),
        plan_only=plan_only,
        branch_unresolved=branch_unresolved,
        main_dirty=main_dirty,
    )
