"""워크트리 목록 및 커밋 정보 조회 서비스"""

import asyncio
import re
import time
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
    WorktreeInfoLite,
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
_COMMIT_SENTINEL = "__WT_COMMIT__"
PlanScanMap = dict[str, tuple[str, str]]
PlanScanUnresolved = list[dict[str, str]]
PlanScanResult = tuple[PlanScanMap, PlanScanUnresolved]
PlanIndexResult = tuple[PlanScanMap, PlanScanMap, PlanScanUnresolved]
_WorktreeCacheKey = tuple[str, Optional[int]]
_CACHE: dict[_WorktreeCacheKey, tuple[WorktreeListResponse, float]] = {}
_CACHE_TTL_SEC = 3.0
_CACHE_LOCKS: dict[_WorktreeCacheKey, asyncio.Lock] = {}


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


def _make_worktree_cache_key(
    repo_root: Path,
    cache_repo_id: Optional[int],
) -> _WorktreeCacheKey:
    """repo_id 단독이 아닌 resolved repo_root + repo_id 조합으로 key를 만든다."""
    resolved_root = str(repo_root.resolve()) if repo_root.exists() else str(repo_root)
    return resolved_root, cache_repo_id


def _get_cache_lock(key: _WorktreeCacheKey) -> asyncio.Lock:
    lock = _CACHE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _CACHE_LOCKS[key] = lock
    return lock


def _cache_get(key: _WorktreeCacheKey) -> Optional[WorktreeListResponse]:
    entry = _CACHE.get(key)
    if entry is None:
        return None

    cached_response, expires_at = entry
    if expires_at <= time.monotonic():
        _CACHE.pop(key, None)
        return None

    return cached_response.model_copy(deep=True)


def _cache_put(key: _WorktreeCacheKey, value: WorktreeListResponse) -> None:
    """캐시 저장 시 deep copy를 남기고, 조회 시에도 deep copy를 반환한다."""
    _CACHE[key] = (value.model_copy(deep=True), time.monotonic() + _CACHE_TTL_SEC)


def invalidate_worktree_cache(key: Optional[_WorktreeCacheKey] = None) -> None:
    if key is None:
        _CACHE.clear()
        _CACHE_LOCKS.clear()
        return

    _CACHE.pop(key, None)
    _CACHE_LOCKS.pop(key, None)


def _iter_active_plan_dirs(repo_root: Path) -> list[Path]:
    """활성 plan 디렉토리만 우선순위 순서대로 반환한다."""
    return [plan_dir for plan_dir, archived in _iter_plan_dirs(repo_root) if not archived]


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
    output = await _run_git(
        "rev-list", "--left-right", "--count", f"main...{branch}", repo_root=repo_root
    )
    if not output:
        return 0, 0

    parts = output.split()
    if len(parts) != 2:
        return 0, 0

    try:
        behind = int(parts[0])
        ahead = int(parts[1])
    except ValueError:
        return 0, 0
    return ahead, behind


async def get_ahead_behind_map(
    branches: list[str],
    repo_root: Path = _REPO_ROOT,
) -> dict[str, tuple[int, int]]:
    """여러 브랜치의 main 대비 ahead/behind를 한 번에 조회한다."""
    requested = [branch for branch in dict.fromkeys(branches) if branch]
    if not requested:
        return {}

    output = await _run_git(
        "for-each-ref",
        "--format=%(refname:short)|%(ahead-behind:refs/heads/main)",
        *[f"refs/heads/{branch}" for branch in requested],
        repo_root=repo_root,
    )
    if not output:
        return {}

    ahead_behind_map: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        if "|" not in line:
            continue
        branch, counts = line.split("|", 1)
        parts = counts.split()
        if len(parts) != 2:
            continue
        try:
            ahead = int(parts[0])
            behind = int(parts[1])
        except ValueError:
            continue
        ahead_behind_map[branch] = (ahead, behind)
    return ahead_behind_map


async def get_worktree_commits(branch: str, repo_root: Path = _REPO_ROOT) -> list[WorktreeCommit]:
    """main 이후 커밋 목록 + 각 커밋의 diff stat 반환 (빈 브랜치 방어)"""
    log_output = await _run_git(
        "log", f"main..{branch}",
        f"--format={_COMMIT_SENTINEL}%H|%ai|%s",
        "--numstat",
        repo_root=repo_root,
    )
    if not log_output:
        return []

    commits: list[WorktreeCommit] = []
    current_commit: Optional[WorktreeCommit] = None
    for line in log_output.splitlines():
        if not line:
            continue

        if line.startswith(_COMMIT_SENTINEL):
            if current_commit is not None:
                commits.append(current_commit)

            parts = line[len(_COMMIT_SENTINEL):].split("|", 2)
            if len(parts) < 3:
                current_commit = None
                continue
            full_hash, date_str, message = parts
            current_commit = WorktreeCommit(
                hash=full_hash,
                short_hash=full_hash[:7],
                message=message,
                date=date_str,
                diff_stat=[],
            )
            continue

        if current_commit is None:
            continue

        parsed = _parse_numstat_line(line)
        if parsed is not None:
            current_commit.diff_stat.append(parsed)

    if current_commit is not None:
        commits.append(current_commit)

    return commits


async def get_created_at(branch: str, repo_root: Path = _REPO_ROOT) -> Optional[str]:
    """main 이후 커밋 중 가장 오래된 커밋의 날짜를 반환한다."""
    output = await _run_git(
        "log", f"main..{branch}", "--format=%ai", "--reverse", repo_root=repo_root
    )
    if not output:
        return None

    for line in output.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def _parse_numstat(output: str) -> list[CommitDiffStat]:
    """git diff-tree --numstat 출력 파싱 (탭 구분: added\\tdeleted\\tpath)"""
    stats = []
    for line in output.splitlines():
        parsed = _parse_numstat_line(line)
        if parsed is not None:
            stats.append(parsed)
    return stats


def _parse_numstat_line(line: str) -> Optional[CommitDiffStat]:
    parts = line.split("\t", 2)
    if len(parts) < 3:
        return None

    added_str, deleted_str, path = parts
    try:
        added = int(added_str)
        deleted = int(deleted_str)
        changes = f"+{added} -{deleted}"
    except ValueError:
        # 바이너리 파일은 '-' 로 표시됨
        changes = f"{added_str} {deleted_str}"
    return CommitDiffStat(file=path, changes=changes)


def _scan_plan_file_index(repo_root: Path = _REPO_ROOT) -> PlanIndexResult:
    """활성/아카이브 plan 인덱스를 한 번에 스캔한다."""
    branch_pattern = re.compile(r"^>\s*branch:\s*(.+)$")
    active_branch_map: PlanScanMap = {}
    archived_branch_map: PlanScanMap = {}
    unresolved: PlanScanUnresolved = []
    seen_paths: set[str] = set()

    for plan_dir, archived in _iter_plan_dirs(repo_root):
        if not plan_dir.exists():
            continue
        for md_file in sorted(plan_dir.glob("*.md")):
            try:
                relative_path = str(md_file.relative_to(repo_root))
                if relative_path in seen_paths:
                    continue
                seen_paths.add(relative_path)

                mtime_iso = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()
                found_branch: Optional[str] = None

                with open(md_file, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= 30:
                            break
                        matched = branch_pattern.match(line.rstrip())
                        if matched:
                            found_branch = matched.group(1).strip()
                            break

                if found_branch is None:
                    if archived:
                        continue
                    unresolved.append({
                        "plan_file": relative_path,
                        "reason": "missing > branch header",
                        "plan_mtime": mtime_iso,
                    })
                    continue

                target_map = archived_branch_map if archived else active_branch_map
                target_map.setdefault(found_branch, (relative_path, mtime_iso))
            except (OSError, UnicodeDecodeError):
                continue

    return active_branch_map, archived_branch_map, unresolved


def scan_plan_files(repo_root: Path = _REPO_ROOT) -> PlanScanResult:
    """활성 plan 디렉토리를 1회 스캔해 branch map과 unresolved 목록을 반환한다."""
    active_branch_map, _archived_branch_map, unresolved = _scan_plan_file_index(repo_root)
    return active_branch_map, unresolved


def find_plan_file(
    branch: str,
    repo_root: Path = _REPO_ROOT,
) -> tuple[Optional[str], Optional[str], bool]:
    """plan/archive 루트에서 > branch: {branch} 헤더를 찾아 (경로, mtime_iso, archived) 반환.

    매칭 실패 시 (None, None, False) 반환.
    """
    active_branch_map, archived_branch_map, _ = _scan_plan_file_index(repo_root=repo_root)
    active_match = active_branch_map.get(branch)
    if active_match is not None:
        path, mtime = active_match
        return path, mtime, False

    archived_match = archived_branch_map.get(branch)
    if archived_match is not None:
        path, mtime = archived_match
        return path, mtime, True
    return None, None, False


def _resolve_plan_metadata(
    branch: str,
    active_branch_map: PlanScanMap,
    archived_branch_map: PlanScanMap,
) -> tuple[Optional[str], Optional[str], bool]:
    plan_file, plan_mtime = active_branch_map.get(branch, (None, None))
    if plan_file is not None:
        return plan_file, plan_mtime, False

    plan_file, plan_mtime = archived_branch_map.get(branch, (None, None))
    return plan_file, plan_mtime, plan_file is not None


def list_plan_only_branches(
    existing_branches: set[str],
    repo_root: Path = _REPO_ROOT,
    scan_result: Optional[PlanScanResult] = None,
) -> tuple[list[PlanOnlyBranch], list[BranchUnresolvedPlan]]:
    """활성 plan 루트 스캔 → worktree 없는 plan 브랜치 목록 반환 (sync)

    > branch: 헤더가 있고 existing_branches에 없는 것 → PlanOnlyBranch
    > branch: 헤더가 없는 것 → BranchUnresolvedPlan (reason: missing > branch header)
    """
    plan_only: list[PlanOnlyBranch] = []
    branch_unresolved: list[BranchUnresolvedPlan] = []
    branch_map, unresolved = scan_result if scan_result is not None else scan_plan_files(repo_root=repo_root)

    for branch, (relative_path, mtime_iso) in branch_map.items():
        if branch in existing_branches:
            continue
        plan_only.append(PlanOnlyBranch(
            plan_file=relative_path,
            branch=branch,
            plan_mtime=mtime_iso,
            is_test=is_test_branch(branch),
        ))

    for item in unresolved:
        branch_unresolved.append(BranchUnresolvedPlan(
            plan_file=item["plan_file"],
            reason=item["reason"],
            plan_mtime=item["plan_mtime"],
        ))

    return plan_only, branch_unresolved


async def get_main_dirty(repo_root: Path = _REPO_ROOT) -> MainDirtyStatus:
    """main 브랜치 dirty 파일 목록 반환 — git status --porcelain=v1 -z 파싱"""
    output = await _run_git("status", "--porcelain=v1", "-z", repo_root=repo_root)
    if not output:
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


async def _resolve_ahead_behind(
    branch: str,
    ahead_behind_map: dict[str, tuple[int, int]],
    repo_root: Path,
) -> tuple[int, int]:
    ahead_behind = ahead_behind_map.get(branch)
    if ahead_behind is None:
        ahead_behind = await get_ahead_behind(branch, repo_root=repo_root)
    return ahead_behind


async def _collect_worktree_state(
    *,
    repo_root: Path,
    worktree_builder,
) -> tuple[list[WorktreeInfoLite], list[PlanOnlyBranch], list[BranchUnresolvedPlan], MainDirtyStatus]:
    raw_worktrees = await list_worktrees(repo_root=repo_root)
    ahead_behind_map, plan_index = await asyncio.gather(
        get_ahead_behind_map([wt["branch"] for wt in raw_worktrees], repo_root=repo_root),
        asyncio.to_thread(_scan_plan_file_index, repo_root),
    )
    active_branch_map, archived_branch_map, unresolved = plan_index

    worktrees: list[WorktreeInfoLite] = []
    if raw_worktrees:
        worktrees = list(await asyncio.gather(*[
            worktree_builder(
                wt,
                repo_root=repo_root,
                ahead_behind_map=ahead_behind_map,
                active_branch_map=active_branch_map,
                archived_branch_map=archived_branch_map,
            )
            for wt in raw_worktrees
        ]))

    existing_branches = {wt.branch for wt in worktrees}

    plan_only_result, main_dirty = await asyncio.gather(
        asyncio.to_thread(
            list_plan_only_branches, existing_branches, repo_root, (active_branch_map, unresolved)
        ),
        get_main_dirty(repo_root=repo_root),
    )
    plan_only_list, branch_unresolved_list = plan_only_result
    return worktrees, plan_only_list, branch_unresolved_list, main_dirty

async def _build_worktree_info_lite(
    wt: dict,
    *,
    repo_root: Path,
    ahead_behind_map: dict[str, tuple[int, int]],
    active_branch_map: PlanScanMap,
    archived_branch_map: PlanScanMap,
) -> WorktreeInfoLite:
    """v2용 lite 카드 모델을 구성한다."""
    branch = wt["branch"]
    ahead, behind = await _resolve_ahead_behind(branch, ahead_behind_map, repo_root)
    created_at = await get_created_at(branch, repo_root=repo_root) if ahead > 0 else None
    plan_file, plan_mtime, plan_file_archived = _resolve_plan_metadata(
        branch,
        active_branch_map,
        archived_branch_map,
    )
    return WorktreeInfoLite(
        branch=branch,
        worktree_path=wt["worktree_path"],
        created_at=created_at,
        ahead=ahead,
        behind=behind,
        locked=wt.get("locked", False),
        commit_count=ahead,
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


async def _build_worktree_info_full(
    wt: dict,
    *,
    repo_root: Path,
    ahead_behind_map: dict[str, tuple[int, int]],
    active_branch_map: PlanScanMap,
    archived_branch_map: PlanScanMap,
) -> WorktreeInfo:
    branch = wt["branch"]
    ahead, behind = await _resolve_ahead_behind(branch, ahead_behind_map, repo_root)
    commits = []
    if ahead > 0:
        commits = await get_worktree_commits(branch, repo_root=repo_root)
    plan_file, plan_mtime, plan_file_archived = _resolve_plan_metadata(
        branch,
        active_branch_map,
        archived_branch_map,
    )
    created_at = commits[-1].date if commits else None
    return WorktreeInfo(
        branch=branch,
        worktree_path=wt["worktree_path"],
        created_at=created_at,
        ahead=ahead,
        behind=behind,
        locked=wt.get("locked", False),
        commit_count=ahead,
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


async def _compute_worktree_list_response(repo_root: Path = _REPO_ROOT) -> WorktreeListResponse:
    """실제 v2 응답 계산 로직."""
    worktrees, plan_only, branch_unresolved, main_dirty = await _collect_worktree_state(
        repo_root=repo_root,
        worktree_builder=_build_worktree_info_lite,
    )
    return WorktreeListResponse(
        worktrees=worktrees,
        plan_only=plan_only,
        branch_unresolved=branch_unresolved,
        main_dirty=main_dirty,
    )


async def get_all_worktrees(
    repo_root: Path = _REPO_ROOT,
    *,
    use_cache: bool = False,
    cache_repo_id: Optional[int] = None,
    force: bool = False,
) -> WorktreeListResponse:
    """v2 lite 워크트리 목록 — 선택적으로 repo_root + repo_id 기반 TTL 캐시를 사용한다."""
    if not use_cache:
        return await _compute_worktree_list_response(repo_root=repo_root)

    cache_key = _make_worktree_cache_key(repo_root, cache_repo_id)
    if not force:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    async with _get_cache_lock(cache_key):
        if not force:
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

        response = await _compute_worktree_list_response(repo_root=repo_root)
        _cache_put(cache_key, response)
        return response.model_copy(deep=True)


async def get_all_worktrees_full(repo_root: Path = _REPO_ROOT) -> list[WorktreeInfo]:
    """v1 full 워크트리 목록 — 커밋 상세 포함."""
    worktrees, _plan_only, _branch_unresolved, _main_dirty = await _collect_worktree_state(
        repo_root=repo_root,
        worktree_builder=_build_worktree_info_full,
    )
    return [WorktreeInfo.model_validate(worktree) for worktree in worktrees]


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
