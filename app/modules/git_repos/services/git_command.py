"""Git CLI 래퍼 서비스."""
import asyncio
import re
from typing import List, Tuple, Optional

from app.modules.git_repos.schemas import LogEntry, RepoStatus

# 위험한 git 인자 패턴 (보안 검증용)
_DANGEROUS_ARGS = {
    "--force", "-f", "--hard", "-D",
    "--force-with-lease", "clean",
    "--delete",
}


class GitCommandService:
    """git CLI를 asyncio로 실행하는 래퍼."""

    TIMEOUT = 30  # 초

    async def _run_git(self, repo_path: str, *args: str) -> Tuple[int, str, str]:
        """git 명령어 실행. 위험 인자 포함 시 거부."""
        # 보안 검증
        for arg in args:
            if arg in _DANGEROUS_ARGS:
                raise PermissionError(f"금지된 git 인자입니다: {arg}")

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=self.TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return -1, "", f"타임아웃 ({self.TIMEOUT}초)"

            return (
                proc.returncode,
                stdout_b.decode("utf-8", errors="replace").strip(),
                stderr_b.decode("utf-8", errors="replace").strip(),
            )
        except FileNotFoundError:
            return -1, "", "git 명령어를 찾을 수 없습니다."

    # ─────────────────────────────────────────────
    # 읽기 작업
    # ─────────────────────────────────────────────

    async def get_status(self, path: str) -> RepoStatus:
        """git status --porcelain=v1 -b 파싱."""
        rc, stdout, stderr = await self._run_git(path, "status", "--porcelain=v1", "-b")
        if rc != 0:
            return RepoStatus(branch="unknown", status="unknown")

        lines = stdout.splitlines()
        branch = "unknown"
        upstream = None
        ahead = 0
        behind = 0
        staged: List[str] = []
        unstaged: List[str] = []
        untracked: List[str] = []

        for line in lines:
            if line.startswith("## "):
                # ## main...origin/main [ahead 1, behind 2]
                header = line[3:]
                # branch 이름
                branch_part = header.split("...")[0].split(" ")[0]
                branch = branch_part if branch_part != "No commits yet on" else "초기 커밋 없음"

                # upstream
                if "..." in header:
                    rest = header.split("...", 1)[1]
                    upstream = rest.split(" ")[0]
                    ahead_m = re.search(r"ahead (\d+)", rest)
                    behind_m = re.search(r"behind (\d+)", rest)
                    if ahead_m:
                        ahead = int(ahead_m.group(1))
                    if behind_m:
                        behind = int(behind_m.group(1))
                continue

            if len(line) < 2:
                continue

            xy = line[:2]
            filename = line[3:]

            # Rename 처리: "old -> new"
            if " -> " in filename:
                filename = filename.split(" -> ")[-1]

            x, y = xy[0], xy[1]

            if xy == "??":
                untracked.append(filename)
            else:
                if x != " " and x != "?":
                    staged.append(filename)
                if y != " " and y != "?":
                    unstaged.append(filename)

        if staged or unstaged or untracked:
            # 충돌 감지: xy 패턴 중 UU, AA, DD 등
            conflict_patterns = {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}
            has_conflict = any(
                line[:2] in conflict_patterns
                for line in lines if len(line) >= 2
            )
            status = "conflict" if has_conflict else "dirty"
        else:
            status = "clean"

        return RepoStatus(
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            status=status,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
        )

    async def get_remote_diff(self, path: str) -> Tuple[int, int]:
        """(ahead, behind) 반환. upstream이 없으면 (0, 0)."""
        rc, stdout, _ = await self._run_git(
            path, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
        )
        if rc != 0:
            return 0, 0
        parts = stdout.split()
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
        return 0, 0

    async def get_diff(self, path: str, staged: bool = False) -> str:
        """diff 전문 반환."""
        args = ["diff"]
        if staged:
            args.append("--cached")
        rc, stdout, _ = await self._run_git(path, *args)
        return stdout if rc == 0 else ""

    async def get_file_diff(self, path: str, file: str, staged: bool = False) -> str:
        """특정 파일 diff."""
        args = ["diff"]
        if staged:
            args.append("--cached")
        args += ["--", file]
        rc, stdout, _ = await self._run_git(path, *args)
        return stdout if rc == 0 else ""

    async def get_log(self, path: str, n: int = 20) -> List[LogEntry]:
        """최근 커밋 로그 파싱."""
        rc, stdout, _ = await self._run_git(
            path, "log", f"-{n}",
            "--pretty=format:%H|%h|%s|%an|%ad",
            "--date=short"
        )
        if rc != 0 or not stdout:
            return []

        entries = []
        for line in stdout.splitlines():
            parts = line.split("|", 4)
            if len(parts) == 5:
                entries.append(LogEntry(
                    hash=parts[0],
                    short_hash=parts[1],
                    message=parts[2],
                    author=parts[3],
                    date=parts[4],
                ))
        return entries

    # ─────────────────────────────────────────────
    # 쓰기 작업
    # ─────────────────────────────────────────────

    async def stage_files(self, path: str, files: List[str]) -> Tuple[bool, str, str]:
        """git add {files}."""
        if not files:
            return False, "", "파일 목록이 비어 있습니다."
        rc, stdout, stderr = await self._run_git(path, "add", "--", *files)
        return rc == 0, stdout, stderr

    async def stage_all(self, path: str) -> Tuple[bool, str, str]:
        """git add -A."""
        rc, stdout, stderr = await self._run_git(path, "add", "-A")
        return rc == 0, stdout, stderr

    async def unstage_files(self, path: str, files: List[str]) -> Tuple[bool, str, str]:
        """git restore --staged {files}."""
        if not files:
            return False, "", "파일 목록이 비어 있습니다."
        rc, stdout, stderr = await self._run_git(path, "restore", "--staged", "--", *files)
        return rc == 0, stdout, stderr

    async def commit(self, path: str, message: str) -> Tuple[bool, str, str]:
        """git commit -m."""
        rc, stdout, stderr = await self._run_git(path, "commit", "-m", message)
        return rc == 0, stdout, stderr

    async def push(self, path: str) -> Tuple[bool, str, str]:
        """git push."""
        rc, stdout, stderr = await self._run_git(path, "push")
        return rc == 0, stdout, stderr

    async def pull(self, path: str) -> Tuple[bool, str, str]:
        """git pull --no-rebase."""
        rc, stdout, stderr = await self._run_git(path, "pull", "--no-rebase")
        return rc == 0, stdout, stderr

    async def fetch(self, path: str) -> Tuple[bool, str, str]:
        """git fetch."""
        rc, stdout, stderr = await self._run_git(path, "fetch")
        return rc == 0, stdout, stderr

    async def stash_save(self, path: str, message: Optional[str] = None) -> Tuple[bool, str, str]:
        """git stash push -m <message>."""
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        rc, stdout, stderr = await self._run_git(path, *args)
        return rc == 0, stdout, stderr

    async def stash_pop(self, path: str) -> Tuple[bool, str, str]:
        """git stash pop."""
        rc, stdout, stderr = await self._run_git(path, "stash", "pop")
        return rc == 0, stdout, stderr
