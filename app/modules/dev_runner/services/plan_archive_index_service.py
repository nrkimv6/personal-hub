"""Plan archive chunking and incremental indexing."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordFileRef,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.services.plan_archive_file_ref_service import extract_file_refs
from app.modules.dev_runner.services.plan_archive_git_index_service import PlanArchiveGitIndexService

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TODO_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\[[ xX]\]\s+")


@dataclass(frozen=True)
class ChunkInput:
    chunk_index: int
    section_type: str
    heading: str | None
    text: str
    content_hash: str
    token_estimate: int


def _estimate_tokens(text: str) -> int:
    return max(1, len(re.findall(r"\S+", text)))


def _section_type(heading: str | None, text: str) -> str:
    haystack = f"{heading or ''}\n{text}".lower()
    if "todo" in haystack or TODO_RE.search(text):
        return "todo"
    if "검증" in haystack or "validation" in haystack or "test" in haystack:
        return "validation"
    if "risk" in haystack or "리스크" in haystack or "주의" in haystack:
        return "risk"
    if heading:
        return "section"
    return "body"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_long_text(text: str, max_words: int = 350) -> Iterable[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        words = _estimate_tokens(paragraph)
        if current and current_words + words > max_words:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(paragraph)
        current_words += words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_plan_into_chunks(raw_content: str) -> list[ChunkInput]:
    """Split markdown plan content into stable evidence chunks."""
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    buffer: list[str] = []
    for line in (raw_content or "").splitlines():
        match = HEADING_RE.match(line)
        if match:
            if buffer:
                sections.append((heading, buffer))
            heading = match.group(2).strip()
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        sections.append((heading, buffer))

    chunks: list[ChunkInput] = []
    for section_heading, lines in sections:
        text = "\n".join(lines).strip()
        if not text:
            continue
        for part in _split_long_text(text):
            chunks.append(
                ChunkInput(
                    chunk_index=len(chunks),
                    section_type=_section_type(section_heading, part),
                    heading=section_heading,
                    text=part,
                    content_hash=_hash_text(part),
                    token_estimate=_estimate_tokens(part),
                )
            )
    return chunks


class PlanArchiveIndexService:
    """Build searchable chunk and file-ref cache for archived plan records."""

    def __init__(self, db: Session, repo_root: str | Path):
        self.db = db
        self.repo_root = Path(repo_root)

    def index_record(self, record_id: int, force: bool = False, dry_run: bool = False) -> dict:
        run = PlanRecordSearchRun(
            plan_record_id=record_id,
            run_type="index_record",
            status="running",
            dry_run=dry_run,
            force=force,
            started_at=datetime.now(),
        )
        self.db.add(run)
        self.db.flush()
        try:
            record = self.db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
            if not record:
                raise ValueError(f"record not found: {record_id}")
            raw_content = record.raw_content
            if not raw_content and record.file_path and Path(record.file_path).exists():
                raw_content = Path(record.file_path).read_text(encoding="utf-8", errors="replace")
            if not raw_content:
                raise ValueError("record has no raw_content and file_path fallback failed")

            chunks = split_plan_into_chunks(raw_content)
            mentioned_refs = extract_file_refs(raw_content, self.repo_root)
            git_refs = []
            try:
                git_refs = PlanArchiveGitIndexService(self.repo_root).collect_changed_refs(record)
            except Exception as exc:
                logger.warning("git-derived refs skipped for plan record %s: %s", record_id, exc)

            result = {
                "record_id": record_id,
                "chunks": len(chunks),
                "mentioned_file_refs": len(mentioned_refs),
                "git_changed_file_refs": len(git_refs),
                "dry_run": dry_run,
            }
            if dry_run:
                run.status = "completed"
                run.indexed_count = 1
                run.detail = result
                run.finished_at = datetime.now()
                return result

            existing_chunks = {
                chunk.chunk_index: chunk
                for chunk in self.db.query(PlanRecordChunk)
                .filter(PlanRecordChunk.plan_record_id == record.id)
                .all()
            }
            chunk_by_index: dict[int, PlanRecordChunk] = {}
            for chunk in chunks:
                row = existing_chunks.get(chunk.chunk_index)
                if not row:
                    row = PlanRecordChunk(plan_record_id=record.id, chunk_index=chunk.chunk_index)
                    self.db.add(row)
                row.section_type = chunk.section_type
                row.heading = chunk.heading
                row.text = chunk.text
                row.content_hash = chunk.content_hash
                row.token_estimate = chunk.token_estimate
                row.updated_at = datetime.now()
                chunk_by_index[chunk.chunk_index] = row
            for stale_index, stale in existing_chunks.items():
                if stale_index not in chunk_by_index:
                    self.db.delete(stale)
            self.db.flush()

            self.db.query(PlanRecordFileRef).filter(PlanRecordFileRef.plan_record_id == record.id).delete()
            for ref in mentioned_refs:
                self.db.add(
                    PlanRecordFileRef(
                        plan_record_id=record.id,
                        chunk_id=chunk_by_index.get(ref.chunk_index).id if ref.chunk_index in chunk_by_index else None,
                        source_type=ref.source_type,
                        path=ref.path,
                        module=ref.module,
                        evidence=ref.evidence,
                        exists_at_index=ref.exists_at_index,
                        first_seen_at=datetime.now(),
                        last_seen_at=datetime.now(),
                    )
                )
            for ref in git_refs:
                self.db.add(
                    PlanRecordFileRef(
                        plan_record_id=record.id,
                        source_type=ref.source_type,
                        path=ref.path,
                        module=ref.module,
                        change_type=ref.change_type,
                        commit_sha=ref.commit_sha,
                        commit_date=ref.commit_date,
                        lines_added=ref.lines_added,
                        lines_deleted=ref.lines_deleted,
                        evidence=ref.evidence,
                        exists_at_index=ref.exists_at_index,
                        first_seen_at=ref.commit_date or datetime.now(),
                        last_seen_at=ref.commit_date or datetime.now(),
                    )
                )
            run.status = "completed"
            run.indexed_count = 1
            run.detail = result
            run.finished_at = datetime.now()
            return result
        except Exception as exc:
            run.status = "failed"
            run.failed_count = 1
            run.error_message = str(exc)
            run.finished_at = datetime.now()
            if not dry_run:
                self.db.flush()
            raise

    def index_archived_records(
        self,
        limit: int = 50,
        force: bool = False,
        since: datetime | None = None,
        dry_run: bool = True,
    ) -> dict:
        query = self.db.query(PlanRecord).filter(PlanRecord.archived_at.isnot(None))
        if since:
            query = query.filter(PlanRecord.archived_at >= since)
        records = query.order_by(PlanRecord.archived_at.desc()).limit(limit).all()
        summary = {"dry_run": dry_run, "indexed": 0, "failed": 0, "skipped": 0, "errors": []}
        for record in records:
            if not force and record.chunks:
                summary["skipped"] += 1
                continue
            try:
                self.index_record(record.id, force=force, dry_run=dry_run)
                summary["indexed"] += 1
            except Exception as exc:
                summary["failed"] += 1
                summary["errors"].append(f"{record.id}: {exc}")
        return summary
