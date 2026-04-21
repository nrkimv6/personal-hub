"""워크트리 목록 및 커밋 정보 조회 서비스"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.modules.dev_runner.schemas import (
    BranchUnresolvedPlan,
    CommitDiffStat,
    MainDirtyStatus,
    PlanOnlyBranch,
    WorktreeCleanupResponse,
    WorktreeCleanupResult,
    WorktreeCommit,
    WorktreeInfo,
    WorktreeListResponse,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # monitor-page 루트
TEST_BRANCH_PATTERNS = (
    re.compile(r"^runner/t-"),
    re.compile(r"^runner/t5"),
    re.compile(r"^plan/test_"),
    re.compile(r"^plan/t-test"),
)
_cleanup_lock = asyncio.Lock()


def _iter_plan_dirs(repo_root: Path) -> list[tuple[Path, bool]]:
    """plan 디렉토리 후보를 우선순위 순서대로 반환.

    우선순위:
    1) .worktrees/plans/docs/plan (활성 plan SSOT)
    2) docs/plan (legacy 활성 plan fallback)
    3) .worktrees/plans/docs/archive (archive SSOT)
    4) docs/archive (legacy archive fallback)
    """
    candidates = [
        (repo_root / ".worktrees" / "plans" / "docs" / "plan", False),
        (repo_root / "docs" / "plan", False),
        (repo_root / ".worktrees" / "plans" / "docs" / "archive", True),
        (repo_root / "docs" / "archive", True),
    ]
    deduped: list[tuple[Path, bool]] = []
    seen: set[str] = set()
    for candidate, archived in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((candidate, archived))
    return deduped


def is_test_branch(branch: str) -> bool:
    return any(pattern.match(branch) for pattern in TEST_BRANCH_PATTERNS)


def compute_cleanable(
    *,
    locked: bool,
    ahead: int,
    plan_file: Optional[str],
    archived: bool,
) -> bool:
    if locked:
        return False
    if ahead != 0:
        return False
    if plan_file is None:
        return True
    return archived


async def _run_git_exec(*args: str, repo_root: Path = _REPO_ROOT) -> tuple[int, str, str]:
    """git 명령 실행 헬퍼 — returncode/stdout/stderr를 반환한다."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-c", "safe.directory=*", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(repo_root),
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except Exception as exc:
        return 1, "", str(exc)


async def _run_git(*args: str, repo_root: Path = _REPO_ROOT) -> str:
    """git 명령 실행 헬퍼 — 실패 시 빈 문자열 반환.

    `-c safe.directory=*`를 자동 주입하여 NSSM SYSTEM 계정에서 실행 시
    git 2.35.2+의 dubious ownership 에러를 방지한다.

    ⚠️ 중복 주의: scripts/worktree_manager.py:_run_git에도 동일한 safe.directory
    주입 로직이 있다. 하나를 수정할 때 반드시 다른 쪽도 함께 확인할 것.
    """
    returncode, stdout, _stderr = await _run_git_exec(*args, repo_root=repo_root)
    if returncode != 0:
        return ""
    return stdout.strip()


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
            block = {"worktree_path": line[len("worktree "):].strip(), "locked": False, "prunable": False}
        elif line.startswith("HEAD "):
            block["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            raw = line[len("branch "):].strip()
            block["branch"] = raw.removeprefix("refs/heads/")
        elif line == "detached":
            block["detached"] = True
        elif line.startswith("locked"):
            block["locked"] = True
        elif line.startswith("prunable"):
            block["prunable"] = True

    if block:
        _maybe_append(block, result)

    return result


def _maybe_append(block: dict, result: list) -> None:
    """detached HEAD, prunable, branch == main 제외"""
    if block.get("detached"):
        return
    if block.get("prunable"):
        return
    branch = block.get("branch", "")
    if branch == "main":
        return
    result.append(block)


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
        _run_git("diff-tree", "--no-commit-id", "-r", "--numstat", h, repo_root=repo_root)
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


def find_plan_file(
    branch: str,
    repo_root: Path = _REPO_ROOT,
) -> tuple[Optional[str], Optional[str], bool]:
    """plan/archive 루트에서 > branch: {branch} 헤더를 찾아 (경로, mtime_iso, archived) 반환.

    매칭 실패 시 (None, None, False) 반환.
    """
    pattern = re.compile(rf"^>\s*branch:\s*{re.escape(branch)}\s*$")
    for plan_dir, archived in _iter_plan_dirs(repo_root):
        if not plan_dir.exists():
            continue
        for md_file in sorted(plan_dir.glob("*.md")):
            try:
                with open(md_file, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= 20:
                            break
                        if pattern.match(line.rstrip()):
                            mtime_iso = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()
                            return str(md_file.relative_to(repo_root)), mtime_iso, archived
            except (OSError, UnicodeDecodeError):
                continue
    return None, None, False


def list_plan_only_branches(
    existing_branches: set[str],
    repo_root: Path = _REPO_ROOT,
) -> tuple[list[PlanOnlyBranch], list[BranchUnresolvedPlan]]:
    """활성 plan 루트 스캔 → worktree 없는 plan 브랜치 목록 반환 (sync)

    > branch: 헤더가 있고 existing_branches에 없는 것 → PlanOnlyBranch
    > branch: 헤더가 없는 것 → BranchUnresolvedPlan (reason: missing > branch header)
    """
    branch_pattern = re.compile(r"^>\s*branch:\s*(.+)$")
    plan_only: list[PlanOnlyBranch] = []
    branch_unresolved: list[BranchUnresolvedPlan] = []
    seen_paths: set[str] = set()
    seen_plan_only_branches: set[str] = set()

    for plan_dir, archived in _iter_plan_dirs(repo_root):
        if not plan_dir.exists():
            continue
        for md_file in sorted(plan_dir.glob("*.md")):
            try:
                mtime_iso = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()
                relative_path = str(md_file.relative_to(repo_root))
                if relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)
                found_branch: Optional[str] = None

                with open(md_file, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= 30:
                            break
                        m = branch_pattern.match(line.rstrip())
                        if m:
                            found_branch = m.group(1).strip()
                            break

                if found_branch is None:
                    if archived:
                        continue
                    branch_unresolved.append(BranchUnresolvedPlan(
                        plan_file=relative_path,
                        reason="missing > branch header",
                        plan_mtime=mtime_iso,
                    ))
                elif archived:
                    continue
                elif found_branch not in existing_branches and found_branch not in seen_plan_only_branches:
                    seen_plan_only_branches.add(found_branch)
                    plan_only.append(PlanOnlyBranch(
                        plan_file=relative_path,
                        branch=found_branch,
                        plan_mtime=mtime_iso,
                        is_test=is_test_branch(found_branch),
                    ))

            except (OSError, UnicodeDecodeError):
                continue

    return plan_only, branch_unresolved


async def get_main_dirty(repo_root: Path = _REPO_ROOT) -> MainDirtyStatus:
    """main 브랜치 dirty 파일 목록 반환 — git status --porcelain=v1 -z 파싱"""
    returncode, output, _stderr = await _run_git_exec("status", "--porcelain=v1", "-z", repo_root=repo_root)
    if returncode != 0 or not output:
        return MainDirtyStatus()

    files: list[str] = []
    records = output.split("\0")
    i = 0
    while i < len(records):
        record = records[i]
        if not record:
            i += 1
            continue
        if len(record) < 3:
            i += 1
            continue
        xy = record[:2]
        path = record[3:]
        # rename/copy: 다음 토큰이 대상 경로
        if xy[0] in ("R", "C"):
            i += 1
            if i < len(records) and records[i]:
                files.append(records[i])
            else:
                files.append(path)
        else:
            files.append(path)
        i += 1

    return MainDirtyStatus(dirty_count=len(files), files=files)


async def get_all_worktrees(repo_root: Path = _REPO_ROOT) -> WorktreeListResponse:
    """전체 워크트리 정보 조합 — ahead/behind + 커밋 목록은 병렬, find_plan_file은 asyncio.to_thread"""
    raw_worktrees = await list_worktrees(repo_root=repo_root)

    async def _build(wt: dict) -> WorktreeInfo:
        branch = wt["branch"]
        (ahead, behind), commits, (plan_file, plan_mtime, plan_file_archived) = await asyncio.gather(
            get_ahead_behind(branch, repo_root=repo_root),
            get_worktree_commits(branch, repo_root=repo_root),
            asyncio.to_thread(find_plan_file, branch, repo_root),
        )
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
            is_test=is_test_branch(branch),
            plan_file_archived=plan_file_archived,
            cleanable=compute_cleanable(
                locked=wt.get("locked", False),
                ahead=ahead,
                plan_file=plan_file,
                archived=plan_file_archived,
            ),
        )

    worktrees: list[WorktreeInfo] = []
    if raw_worktrees:
        worktrees = list(await asyncio.gather(*[_build(wt) for wt in raw_worktrees]))

    existing_branches = {wt.branch for wt in worktrees}

    plan_only_result, main_dirty = await asyncio.gather(
        asyncio.to_thread(list_plan_only_branches, existing_branches, repo_root),
        get_main_dirty(repo_root=repo_root),
    )
    plan_only_list, branch_unresolved_list = plan_only_result

    return WorktreeListResponse(
        worktrees=worktrees,
        plan_only=plan_only_list,
        branch_unresolved=branch_unresolved_list,
        main_dirty=main_dirty,
    )


async def cleanup_worktrees(
    branches: list[str],
    dry_run: bool,
    repo_root: Path = _REPO_ROOT,
) -> WorktreeCleanupResponse:
    requested = [branch for branch in dict.fromkeys(branches) if branch]
    if not requested:
        return WorktreeCleanupResponse(
            results=[],
            summary={"requested": 0, "removed": 0, "skipped": 0, "failed": 0},
        )

    async with _cleanup_lock:
        raw_worktrees = await list_worktrees(repo_root=repo_root)
        worktree_by_branch = {wt["branch"]: wt for wt in raw_worktrees}
        results: list[WorktreeCleanupResult] = []

        for branch in requested:
            wt = worktree_by_branch.get(branch)
            if wt is None:
                results.append(WorktreeCleanupResult(
                    branch=branch,
                    status="skipped",
                    reason="worktree not found",
                ))
                continue

            ahead, _behind = await get_ahead_behind(branch, repo_root=repo_root)
            plan_file, _plan_mtime, archived = await asyncio.to_thread(find_plan_file, branch, repo_root)
            cleanable = compute_cleanable(
                locked=wt.get("locked", False),
                ahead=ahead,
                plan_file=plan_file,
                archived=archived,
            )
            if not cleanable:
                reasons: list[str] = []
                if wt.get("locked", False):
                    reasons.append("locked")
                if ahead != 0:
                    reasons.append(f"ahead={ahead}")
                if plan_file and not archived:
                    reasons.append("active plan linked")
                results.append(WorktreeCleanupResult(
                    branch=branch,
                    status="skipped",
                    reason=", ".join(reasons) or "not cleanable",
                ))
                continue

            if dry_run:
                results.append(WorktreeCleanupResult(
                    branch=branch,
                    status="skipped",
                    reason="dry_run",
                ))
                continue

            worktree_removed = False
            branch_removed = False
            remove_rc, _remove_out, remove_err = await _run_git_exec(
                "worktree", "remove", "--force", wt["worktree_path"],
                repo_root=repo_root,
            )
            if remove_rc == 0 or "is not a working tree" in remove_err:
                worktree_removed = True
            else:
                results.append(WorktreeCleanupResult(
                    branch=branch,
                    status="failed",
                    reason=remove_err.strip() or "git worktree remove failed",
                    worktree_removed=False,
                    branch_removed=False,
                ))
                continue

            branch_rc, _branch_out, branch_err = await _run_git_exec(
                "branch", "-D", branch,
                repo_root=repo_root,
            )
            if branch_rc == 0 or "not found" in branch_err or "branch '" in branch_err:
                branch_removed = branch_rc == 0 or "not found" in branch_err
                results.append(WorktreeCleanupResult(
                    branch=branch,
                    status="removed",
                    worktree_removed=worktree_removed,
                    branch_removed=branch_removed,
                ))
                continue

            results.append(WorktreeCleanupResult(
                branch=branch,
                status="failed",
                reason=branch_err.strip() or "git branch -D failed",
                worktree_removed=worktree_removed,
                branch_removed=False,
            ))

        summary = {
            "requested": len(requested),
            "removed": sum(1 for result in results if result.status == "removed"),
            "skipped": sum(1 for result in results if result.status == "skipped"),
            "failed": sum(1 for result in results if result.status == "failed"),
        }
        return WorktreeCleanupResponse(results=results, summary=summary)
