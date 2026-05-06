"""Git-derived file reference indexing for archived plans."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.modules.dev_runner.services.plan_archive_file_ref_service import module_from_path, normalize_repo_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitChangedFileRef:
    path: str
    source_type: str = "git_changed"
    repo_key: str = "monitor-page"
    repo_root: str | None = None
    repo_commit_sha: str | None = None
    module: str | None = None
    change_type: str | None = None
    commit_sha: str | None = None
    commit_date: datetime | None = None
    lines_added: int | None = None
    lines_deleted: int | None = None
    evidence: str | None = None
    exists_at_index: bool = False


class PlanArchiveGitIndexService:
    """Collect changed files from git as retrieval evidence.

    MVP heuristic: use a bounded commit window around the plan archived/applied
    date, or the most recent commits when no date exists. Git remains the source
    of truth; DB rows are only a searchable cache.
    """

    def __init__(self, repo_root: str | Path, repo_key: str = "monitor-page"):
        self.repo_root = Path(repo_root)
        self.repo_key = repo_key

    def collect_changed_refs(self, record, max_commits: int = 30) -> list[GitChangedFileRef]:
        since_until: list[str] = []
        anchor = getattr(record, "applied_at", None) or getattr(record, "archived_at", None)
        if anchor:
            since = (anchor - timedelta(days=7)).date().isoformat()
            until = (anchor + timedelta(days=7)).date().isoformat()
            since_until = [f"--since={since}", f"--until={until}"]

        args = [
            "git",
            "-C",
            str(self.repo_root),
            "log",
            f"--max-count={max_commits}",
            "--name-status",
            "--pretty=format:--COMMIT--%H%x09%cI",
            *since_until,
        ]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        except Exception as exc:
            logger.warning("plan archive git index command failed: %s", exc)
            raise RuntimeError(f"git index command failed: {exc}") from exc
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "git log failed").strip())
        return self._parse_name_status(proc.stdout)

    def _parse_name_status(self, output: str) -> list[GitChangedFileRef]:
        refs: dict[tuple[str, str | None], GitChangedFileRef] = {}
        commit_sha: str | None = None
        commit_date: datetime | None = None
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("--COMMIT--"):
                payload = line.removeprefix("--COMMIT--")
                parts = payload.split("\t", 1)
                commit_sha = parts[0] or None
                commit_date = None
                if len(parts) > 1:
                    try:
                        commit_date = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
                    except ValueError:
                        commit_date = None
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            change_type = cols[0]
            path = normalize_repo_path(cols[-1])
            if not path or path.startswith(".worktrees/"):
                continue
            key = (path, commit_sha)
            refs[key] = GitChangedFileRef(
                path=path,
                repo_key=self.repo_key,
                repo_root=str(self.repo_root),
                repo_commit_sha=commit_sha,
                module=module_from_path(path),
                change_type=change_type[:20],
                commit_sha=commit_sha,
                commit_date=commit_date,
                evidence=line,
                exists_at_index=(self.repo_root / path).exists(),
            )
        return list(refs.values())
