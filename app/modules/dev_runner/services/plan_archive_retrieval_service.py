"""Deterministic retrieval over archived plan metadata, chunks, and file refs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import String, func, or_
from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_semantic_search_service import PlanArchiveSemanticSearchService


@dataclass(frozen=True)
class RetrievalQuery:
    q: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    category: str | None = None
    tags: list[str] | None = None
    intent: str | None = None
    scope: str | None = None
    path: str | None = None
    repo_key: str | None = None
    relation_type: str | None = None
    semantic_cluster_id: str | None = None
    limit: int = 20


def _tags_contain(record_tags: Any, requested: list[str] | None) -> bool:
    if not requested:
        return True
    tags = record_tags or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [tags]
    return all(tag in tags for tag in requested)


def _snippet(text: str, q: str | None, width: int = 220) -> str:
    if not text:
        return ""
    if not q:
        return text[:width]
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:width]
    start = max(0, idx - 80)
    end = min(len(text), idx + len(q) + 140)
    return text[start:end]


def _looks_like_path_query(q: str | None) -> bool:
    if not q:
        return False
    if "/" in q or "\\" in q:
        return True
    return " " not in q and "." in q


def semantic_cluster_evidence_filter(cluster_id: str):
    evidence_text = PlanRecordRelation.evidence.cast(String)
    return or_(
        evidence_text.ilike(f'%"cluster_id": "{cluster_id}"%'),
        evidence_text.ilike(f'%"cluster_id":"{cluster_id}"%'),
    )


class PlanArchiveRetrievalService:
    def __init__(self, db: Session):
        self.db = db

    def search(self, query: RetrievalQuery) -> dict:
        base = self.db.query(PlanRecord).filter(PlanRecord.archived_at.isnot(None))
        if query.category:
            base = base.filter(PlanRecord.category == query.category)
        if query.intent:
            base = base.filter(PlanRecord.intent.ilike(f"%{query.intent}%"))
        if query.scope:
            base = base.filter(PlanRecord.scope.ilike(f"%{query.scope}%"))
        if query.date_from:
            base = base.filter(PlanRecord.archived_at >= query.date_from)
        if query.date_to:
            base = base.filter(PlanRecord.archived_at <= query.date_to)
        if query.relation_type:
            base = base.join(
                PlanRecordRelation,
                PlanRecordRelation.source_plan_record_id == PlanRecord.id,
            ).filter(PlanRecordRelation.relation_type == query.relation_type)
        if query.semantic_cluster_id:
            base = base.join(
                PlanRecordRelation,
                PlanRecordRelation.source_plan_record_id == PlanRecord.id,
            ).filter(
                PlanRecordRelation.relation_type == "semantic_similar",
                semantic_cluster_evidence_filter(query.semantic_cluster_id),
            )

        records = [record for record in base.limit(max(query.limit * 5, query.limit)).all() if _tags_contain(record.tags, query.tags)]
        record_ids = [record.id for record in records]
        if not record_ids:
            return {"results": [], "total": 0}

        semantic_by_record: dict[int, list[tuple[PlanRecordChunk, float]]] = {rid: [] for rid in record_ids}
        try:
            semantic_hits = PlanArchiveSemanticSearchService(self.db).search_chunks(
                query.q,
                record_ids=record_ids,
                limit=max(query.limit * 5, query.limit),
            )
            for hit in semantic_hits:
                semantic_by_record.setdefault(hit.chunk.plan_record_id, []).append((hit.chunk, hit.score))
        except Exception:
            semantic_hits = []

        chunks_by_record: dict[int, list[PlanRecordChunk]] = {rid: [] for rid in record_ids}
        chunk_query = self.db.query(PlanRecordChunk).filter(PlanRecordChunk.plan_record_id.in_(record_ids))
        if query.q:
            chunk_query = chunk_query.filter(
                or_(
                    PlanRecordChunk.text.ilike(f"%{query.q}%"),
                    PlanRecordChunk.heading.ilike(f"%{query.q}%"),
                )
            )
        for chunk in chunk_query.order_by(PlanRecordChunk.plan_record_id, PlanRecordChunk.chunk_index).all():
            chunks_by_record.setdefault(chunk.plan_record_id, []).append(chunk)

        file_refs_by_record: dict[int, list[PlanRecordFileRef]] = {rid: [] for rid in record_ids}
        file_query = self.db.query(PlanRecordFileRef).filter(PlanRecordFileRef.plan_record_id.in_(record_ids))
        effective_path = query.path or (query.q if _looks_like_path_query(query.q) else None)
        if effective_path:
            normalized_path = effective_path.replace("\\", "/")
            file_query = file_query.filter(PlanRecordFileRef.path.ilike(f"%{normalized_path}%"))
        if query.repo_key:
            file_query = file_query.filter(PlanRecordFileRef.repo_key == query.repo_key)
        for ref in file_query.order_by(PlanRecordFileRef.plan_record_id, PlanRecordFileRef.path).all():
            file_refs_by_record.setdefault(ref.plan_record_id, []).append(ref)

        relation_counts = {
            row[0]: row[1]
            for row in self.db.query(PlanRecordRelation.source_plan_record_id, func.count(PlanRecordRelation.id))
            .filter(PlanRecordRelation.source_plan_record_id.in_(record_ids))
            .group_by(PlanRecordRelation.source_plan_record_id)
            .all()
        }

        results = []
        for record in records:
            chunks = chunks_by_record.get(record.id, [])
            file_refs = file_refs_by_record.get(record.id, [])
            semantic_chunks = semantic_by_record.get(record.id, [])
            lexical_score = len(chunks) * 10 if query.q else 0
            semantic_score = max([score for _, score in semantic_chunks], default=0.0) * 25 if query.q else 0
            file_score = len(file_refs) * 100 if effective_path else 0
            metadata_score = 10
            relation_score = min(20, relation_counts.get(record.id, 0) * 5)
            score = metadata_score + lexical_score + semantic_score + file_score + relation_score
            if query.q and not chunks and not semantic_chunks and not file_refs:
                continue
            if effective_path and not file_refs:
                continue
            merged_chunks = chunks[:]
            existing_chunk_ids = {chunk.id for chunk in merged_chunks}
            semantic_score_by_chunk = {chunk.id: score for chunk, score in semantic_chunks}
            for chunk, _score in semantic_chunks:
                if chunk.id not in existing_chunk_ids:
                    merged_chunks.append(chunk)
                    existing_chunk_ids.add(chunk.id)
            results.append(
                {
                    "plan": record,
                    "score": score,
                    "score_detail": {
                        "metadata": metadata_score,
                        "lexical": lexical_score,
                        "semantic": semantic_score,
                        "file": file_score,
                        "relation": relation_score,
                    },
                    "chunks": [
                        {
                            "id": chunk.id,
                            "section_type": chunk.section_type,
                            "heading": chunk.heading,
                            "text": chunk.text,
                            "snippet": _snippet(chunk.text, query.q),
                            "score": max(10 if chunk in chunks and query.q else 0, semantic_score_by_chunk.get(chunk.id, 0) * 25),
                        }
                        for chunk in merged_chunks[:5]
                    ],
                    "file_refs": [
                        {
                            "id": ref.id,
                            "path": ref.path,
                            "source_type": ref.source_type,
                            "repo_key": ref.repo_key,
                            "module": ref.module,
                            "commit_sha": ref.commit_sha,
                            "exists_at_index": ref.exists_at_index,
                        }
                        for ref in file_refs[:10]
                    ],
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        limited = results[: query.limit]
        return {"results": limited, "total": len(results)}
