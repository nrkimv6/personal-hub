"""Cross-repo git evidence collection for Plan Archive retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.modules.dev_runner.services.plan_archive_git_index_service import (
    GitChangedFileRef,
    PlanArchiveGitIndexService,
)
from app.modules.dev_runner.services.plan_archive_repo_registry import (
    PlanArchiveRepoRegistry,
    RepoRegistryEntry,
)


@dataclass(frozen=True)
class CrossRepoIndexCandidate:
    repo_key: str
    repo_root: Path
    status: str
    refs: list[GitChangedFileRef] = field(default_factory=list)
    error: str | None = None


class PlanArchiveCrossRepoIndexService:
    """Collect git file refs from registered repos without failing the whole batch."""

    def __init__(self, registry: PlanArchiveRepoRegistry | None = None):
        self.registry = registry or PlanArchiveRepoRegistry()

    def collect_candidates(self, record, max_commits: int = 30) -> list[CrossRepoIndexCandidate]:
        candidates: list[CrossRepoIndexCandidate] = []
        for entry in self.registry.list_repos():
            candidates.append(self._collect_repo(entry, record, max_commits=max_commits))
        return candidates

    def _collect_repo(self, entry: RepoRegistryEntry, record, max_commits: int) -> CrossRepoIndexCandidate:
        if entry.status != "ready":
            return CrossRepoIndexCandidate(
                repo_key=entry.repo_key,
                repo_root=entry.repo_root,
                status=entry.status,
                error=entry.reason,
            )
        try:
            refs = PlanArchiveGitIndexService(entry.repo_root).collect_changed_refs(
                record,
                max_commits=max_commits,
            )
        except Exception as exc:
            return CrossRepoIndexCandidate(
                repo_key=entry.repo_key,
                repo_root=entry.repo_root,
                status="failed",
                error=str(exc),
            )
        return CrossRepoIndexCandidate(
            repo_key=entry.repo_key,
            repo_root=entry.repo_root,
            status="ready",
            refs=refs,
        )
