"""워크트리 목록 및 커밋 정보 조회 서비스"""

import asyncio
import re
from pathlib import Path
from typing import Optional

from app.modules.dev_runner.schemas import CommitDiffStat, WorktreeCommit, WorktreeInfo

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent  # monitor-page 루트


async def _run_git(*args: str) -> str:
    """git 명령 실행 헬퍼 — 실패 시 빈 문자열 반환"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_REPO_ROOT),
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return ""
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


async def list_worktrees() -> list[dict]:
    """git worktree list --porcelain 파싱 → 브랜치명 == main 제외, detached HEAD 제외"""
    output = await _run_git("worktree", "list", "--porcelain")
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


async def get_ahead_behind(branch: str) -> tuple[int, int]:
    """main 대비 ahead/behind 커밋 수 반환"""
    ahead_str, behind_str = await asyncio.gather(
        _run_git("rev-list", "--count", f"main..{branch}"),
        _run_git("rev-list", "--count", f"{branch}..main"),
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


async def get_worktree_commits(branch: str) -> list[WorktreeCommit]:
    """main 이후 커밋 목록 + 각 커밋의 diff stat 반환 (빈 브랜치 방어)"""
    log_output = await _run_git(
        "log", f"main..{branch}",
        "--format=%H|%ai|%s",
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


def find_plan_file(branch: str) -> Optional[str]:
    """docs/plan/*.md 에서 > branch: {branch} 헤더를 찾아 경로 반환 (sync)

    기존 plan_scanner/plan_path_resolver에 유사 로직 없으므로 자체 구현.
    """
    plan_dir = _REPO_ROOT / "docs" / "plan"
    if not plan_dir.exists():
        return None

    pattern = re.compile(rf"^>\s*branch:\s*{re.escape(branch)}\s*$")
    for md_file in plan_dir.glob("*.md"):
        try:
            with open(md_file, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    if pattern.match(line.rstrip()):
                        return str(md_file.relative_to(_REPO_ROOT))
        except (OSError, UnicodeDecodeError):
            continue
    return None


async def get_all_worktrees() -> list[WorktreeInfo]:
    """전체 워크트리 정보 조합 — ahead/behind + 커밋 목록은 병렬, find_plan_file은 asyncio.to_thread"""
    raw_worktrees = await list_worktrees()
    if not raw_worktrees:
        return []

    async def _build(wt: dict) -> WorktreeInfo:
        branch = wt["branch"]
        (ahead, behind), commits, plan_file = await asyncio.gather(
            get_ahead_behind(branch),
            get_worktree_commits(branch),
            asyncio.to_thread(find_plan_file, branch),
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
        )

    return list(await asyncio.gather(*[_build(wt) for wt in raw_worktrees]))
