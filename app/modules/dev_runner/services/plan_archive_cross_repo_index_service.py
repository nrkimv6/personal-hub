"""Cross-repo git evidence collection for Plan Archive retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordFileRef, PlanRecordRepoRef
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
            refs = PlanArchiveGitIndexService(entry.repo_root, repo_key=entry.repo_key).collect_changed_refs(
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


class PlanArchiveCrossRepoIndexWriter:
    """Persist cross-repo git evidence for one PlanRecord."""

    def __init__(self, db: Session, registry: PlanArchiveRepoRegistry | None = None):
        self.db = db
        self.collector = PlanArchiveCrossRepoIndexService(registry)

    def index_record(self, record_id: int, *, max_commits: int = 30, dry_run: bool = True) -> dict:
        record = self.db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
        if not record:
            raise ValueError(f"record not found: {record_id}")
        candidates = self.collector.collect_candidates(record, max_commits=max_commits)
        summary = {
            "dry_run": dry_run,
            "record_id": record_id,
            "repos": len(candidates),
            "indexed": sum(len(candidate.refs) for candidate in candidates if candidate.status == "ready"),
            "failed": sum(1 for candidate in candidates if candidate.status == "failed"),
            "skipped": sum(1 for candidate in candidates if candidate.status == "skipped"),
            "errors": [f"{candidate.repo_key}: {candidate.error}" for candidate in candidates if candidate.error],
        }
        if dry_run:
            return summary

        self.db.query(PlanRecordFileRef).filter(
            PlanRecordFileRef.plan_record_id == record.id,
            PlanRecordFileRef.source_type.in_(["git_changed", "downstream_sync"]),
        ).delete(synchronize_session=False)
        self.db.query(PlanRecordRepoRef).filter(
            PlanRecordRepoRef.plan_record_id == record.id,
            PlanRecordRepoRef.source_type == "git_changed",
        ).delete(synchronize_session=False)

        for candidate in candidates:
            self.db.add(
                PlanRecordRepoRef(
                    plan_record_id=record.id,
                    repo_key=candidate.repo_key,
                    repo_root=str(candidate.repo_root),
                    repo_commit_sha=candidate.refs[0].commit_sha if candidate.refs else None,
                    source_type="git_changed",
                    status=candidate.status,
                    error_message=candidate.error,
                )
            )
            if candidate.status != "ready":
                continue
            for ref in candidate.refs:
                source_type = "downstream_sync" if candidate.repo_key in {"monitor-page-plans", "wtools"} else ref.source_type
                self.db.add(
                    PlanRecordFileRef(
                        plan_record_id=record.id,
                        source_type=source_type,
                        repo_key=candidate.repo_key,
                        repo_root=str(candidate.repo_root),
                        repo_commit_sha=ref.repo_commit_sha,
                        path=ref.path,
                        module=ref.module,
                        change_type=ref.change_type,
                        commit_sha=ref.commit_sha,
                        commit_date=ref.commit_date,
                        lines_added=ref.lines_added,
                        lines_deleted=ref.lines_deleted,
                        evidence=ref.evidence,
                        exists_at_index=ref.exists_at_index,
                        first_seen_at=ref.commit_date,
                        last_seen_at=ref.commit_date,
                    )
                )
        return summary
