"""Deterministic plan-to-plan relation tracking from plan body text."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordRelation

logger = logging.getLogger(__name__)

PLAN_BODY_RELATION_TYPES = frozenset(
    {
        "mentions",
        "predecessor",
        "successor",
        "unresolved_followup",
        "cause",
        "guard",
        "supersedes",
    }
)
BODY_RELATION_GENERATOR = "plan_body_relation_tracking"
BODY_RELATION_PARSER_VERSION = 1

PLAN_FILENAME_RE = re.compile(r"(?P<filename>\d{4}-\d{2}-\d{2}[_-][^\s\])`'\"<>]+?\.md)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+?\.md(?:#[^)]+)?(?:\?[^)]*)?)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

RELATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "predecessor": ("직접 선행", "관련 선행", "선행 계획서", "선행"),
    "successor": ("병행 후속", "관련 후속", "후속 계획서", "후속"),
    "unresolved_followup": ("미해결", "미해소", "보존만", "닫지 않았다", "누락된 복구", "이 계획이 닫는다"),
    "cause": ("원인 계획", "범인 계획서", "범인 판정"),
    "guard": ("관련 guard", "방어 선행", "재발 방지", "guard"),
    "supersedes": ("superseded_by", "대체 관계", "대체"),
}

BASE_SCORE = {
    "mentions": 30,
    "predecessor": 75,
    "successor": 75,
    "unresolved_followup": 90,
    "cause": 85,
    "guard": 80,
    "supersedes": 80,
}


@dataclass(frozen=True)
class PlanMention:
    filename: str
    raw_reference: str
    line_number: int
    line_text: str
    heading: str | None = None
    label: str | None = None
    context: str = ""
    source: str = "bare_filename"


@dataclass
class RelationRefreshResult:
    record_id: int
    dry_run: bool = False
    mentions: int = 0
    created: int = 0
    updated: int = 0
    stale_deleted: int = 0
    skipped: list[dict] = field(default_factory=list)
    unresolved_targets: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "dry_run": self.dry_run,
            "mentions": self.mentions,
            "created": self.created,
            "updated": self.updated,
            "stale_deleted": self.stale_deleted,
            "skipped": self.skipped,
            "unresolved_targets": self.unresolved_targets,
            "warnings": self.warnings,
        }


def compute_plan_filename_hash(file_path: str) -> str:
    """Return the same stable filename hash as PlanRecordService."""
    return hashlib.sha256(Path(file_path).name.encode("utf-8")).hexdigest()


def _normalize_plan_filename(value: str) -> str:
    cleaned = unquote((value or "").strip())
    cleaned = cleaned.split("#", 1)[0].split("?", 1)[0]
    cleaned = cleaned.rstrip(".,;:")
    return Path(cleaned.replace("\\", "/")).name


def _context_for_line(lines: list[str], index: int) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + 2)
    return " ".join(line.strip() for line in lines[start:end] if line.strip())


def extract_plan_mentions(raw_content: str) -> list[PlanMention]:
    """Extract explicit plan filename mentions from markdown content."""
    lines = (raw_content or "").splitlines()
    mentions: list[PlanMention] = []
    seen: set[tuple[str, int]] = set()
    heading: str | None = None

    for idx, line in enumerate(lines):
        heading_match = HEADING_RE.match(line)
        if heading_match:
            heading = heading_match.group(2).strip()

        markdown_spans: list[tuple[int, int]] = []
        for match in MARKDOWN_LINK_RE.finditer(line):
            label, target = match.group(1), match.group(2)
            filename = _normalize_plan_filename(target)
            if not PLAN_FILENAME_RE.search(filename):
                continue
            key = (filename, idx + 1)
            if key in seen:
                continue
            seen.add(key)
            markdown_spans.append(match.span())
            mentions.append(
                PlanMention(
                    filename=filename,
                    raw_reference=target,
                    line_number=idx + 1,
                    line_text=line.strip(),
                    heading=heading,
                    label=label.strip() or None,
                    context=_context_for_line(lines, idx),
                    source="markdown_link",
                )
            )

        for match in PLAN_FILENAME_RE.finditer(line):
            if any(start <= match.start() < end for start, end in markdown_spans):
                continue
            filename = _normalize_plan_filename(match.group("filename"))
            key = (filename, idx + 1)
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                PlanMention(
                    filename=filename,
                    raw_reference=match.group("filename"),
                    line_number=idx + 1,
                    line_text=line.strip(),
                    heading=heading,
                    context=_context_for_line(lines, idx),
                    source="bare_filename" if Path(match.group("filename")).name == match.group("filename") else "inline_path",
                )
            )

    return mentions


def _classify_with_keywords(mention: PlanMention) -> tuple[set[str], dict[str, list[str]]]:
    haystack = " ".join(
        part
        for part in (mention.heading, mention.label, mention.line_text, mention.context)
        if part
    )
    relation_types: set[str] = set()
    matched: dict[str, list[str]] = {}
    for relation_type, keywords in RELATION_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword in haystack]
        if hits:
            relation_types.add(relation_type)
            matched[relation_type] = hits
    if not relation_types:
        relation_types.add("mentions")
    return relation_types, matched


def classify_plan_relation(mention: PlanMention) -> set[str]:
    """Classify an extracted mention into body-derived relation types."""
    return _classify_with_keywords(mention)[0]


def _score_relation(relation_type: str, mention: PlanMention) -> int:
    score = BASE_SCORE.get(relation_type, 0)
    haystack = f"{mention.heading or ''}\n{mention.line_text}"
    if "|" in mention.line_text:
        score += 5
    if relation_type != "mentions" and any(keyword in haystack for keyword in RELATION_KEYWORDS.get(relation_type, ())):
        score += 5
    if mention.source == "markdown_link":
        score += 3
    return min(score, 100)


def _relation_has_generator(relation: PlanRecordRelation) -> bool:
    evidence = relation.evidence or {}
    return isinstance(evidence, dict) and evidence.get("generated_by") == BODY_RELATION_GENERATOR


class PlanArchiveRelationService:
    """Refresh explicit plan-body relations for PlanRecord rows."""

    def __init__(self, db: Session):
        self.db = db

    def resolve_target_record(self, filename_or_path: str) -> PlanRecord | None:
        filename = _normalize_plan_filename(filename_or_path)
        if not filename:
            return None
        filename_hash = compute_plan_filename_hash(filename)
        exact = self.db.query(PlanRecord).filter(PlanRecord.filename_hash == filename_hash).first()
        if exact:
            return exact

        suffix = filename.replace("\\", "/")
        candidates = self.db.query(PlanRecord).filter(PlanRecord.file_path.ilike(f"%{suffix}")).all()
        normalized = [record for record in candidates if Path((record.file_path or "").replace("\\", "/")).name == filename]
        if len(normalized) == 1:
            return normalized[0]
        return None

    def _raw_content_for_record(self, record: PlanRecord) -> str:
        if record.raw_content:
            return record.raw_content
        if record.file_path and Path(record.file_path).exists():
            return Path(record.file_path).read_text(encoding="utf-8", errors="replace")
        return ""

    def refresh_relations_for_record(
        self,
        record_id: int,
        *,
        dry_run: bool = False,
        relation_types: Iterable[str] | None = None,
    ) -> RelationRefreshResult:
        allowed_types = set(relation_types or PLAN_BODY_RELATION_TYPES)
        unknown_types = sorted(allowed_types - PLAN_BODY_RELATION_TYPES)
        allowed_types &= PLAN_BODY_RELATION_TYPES
        result = RelationRefreshResult(record_id=record_id, dry_run=dry_run)
        for relation_type in unknown_types:
            result.warnings.append({"relation_type": relation_type, "reason": "unknown_body_relation_type"})

        record = self.db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
        if not record:
            result.skipped.append({"record_id": record_id, "reason": "source_record_not_found"})
            return result

        raw_content = self._raw_content_for_record(record)
        if not raw_content:
            result.skipped.append({"record_id": record_id, "reason": "empty_raw_content"})
            return result

        mentions = extract_plan_mentions(raw_content)
        result.mentions = len(mentions)
        seen_keys: set[tuple[int, int, str]] = set()

        for mention in mentions:
            target = self.resolve_target_record(mention.filename)
            if not target:
                item = {
                    "filename": mention.filename,
                    "line_number": mention.line_number,
                    "reason": "target_not_found_or_ambiguous",
                }
                result.unresolved_targets.append(item)
                result.skipped.append(item)
                continue
            if target.id == record.id:
                result.skipped.append(
                    {
                        "filename": mention.filename,
                        "line_number": mention.line_number,
                        "reason": "self_reference",
                    }
                )
                continue

            classified, keywords = _classify_with_keywords(mention)
            for relation_type in sorted(classified & allowed_types):
                key = (record.id, target.id, relation_type)
                seen_keys.add(key)
                evidence = {
                    "generated_by": BODY_RELATION_GENERATOR,
                    "parser_version": BODY_RELATION_PARSER_VERSION,
                    "filename": mention.filename,
                    "raw_reference": mention.raw_reference,
                    "line_number": mention.line_number,
                    "line_text": mention.line_text,
                    "heading": mention.heading,
                    "label": mention.label,
                    "context": mention.context,
                    "source": mention.source,
                    "matched_keywords": keywords.get(relation_type, []),
                }
                score = _score_relation(relation_type, mention)
                relation = (
                    self.db.query(PlanRecordRelation)
                    .filter(
                        PlanRecordRelation.source_plan_record_id == record.id,
                        PlanRecordRelation.target_plan_record_id == target.id,
                        PlanRecordRelation.relation_type == relation_type,
                    )
                    .first()
                )
                if relation:
                    result.updated += 1
                    if not dry_run:
                        relation.score = score
                        relation.evidence = evidence
                        relation.updated_at = datetime.now()
                else:
                    result.created += 1
                    if not dry_run:
                        self.db.add(
                            PlanRecordRelation(
                                source_plan_record_id=record.id,
                                target_plan_record_id=target.id,
                                relation_type=relation_type,
                                score=score,
                                evidence=evidence,
                            )
                        )

        existing_body_relations = (
            self.db.query(PlanRecordRelation)
            .filter(
                PlanRecordRelation.source_plan_record_id == record.id,
                PlanRecordRelation.relation_type.in_(allowed_types),
            )
            .all()
        )
        for relation in existing_body_relations:
            key = (relation.source_plan_record_id, relation.target_plan_record_id, relation.relation_type)
            if key in seen_keys or not _relation_has_generator(relation):
                continue
            result.stale_deleted += 1
            if not dry_run:
                self.db.delete(relation)

        if not dry_run:
            self.db.flush()
        return result
