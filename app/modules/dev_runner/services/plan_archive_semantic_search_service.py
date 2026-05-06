"""Semantic retrieval adapter for archived plan chunks."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecordChunk, PlanRecordChunkEmbedding
from app.modules.dev_runner.services.plan_archive_embedding_service import (
    PlanArchiveEmbeddingConfig,
    PlanArchiveEmbeddingService,
)


@dataclass(frozen=True)
class SemanticChunkHit:
    chunk: PlanRecordChunk
    score: float


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


class PlanArchiveSemanticSearchService:
    def __init__(
        self,
        db: Session,
        config: PlanArchiveEmbeddingConfig | None = None,
        embedding_service: PlanArchiveEmbeddingService | None = None,
    ):
        self.db = db
        self.embedding_service = embedding_service or PlanArchiveEmbeddingService(db, config=config)
        self.config = self.embedding_service.config

    def search_chunks(self, query_text: str | None, record_ids: list[int] | None = None, limit: int = 20) -> list[SemanticChunkHit]:
        if not query_text or not query_text.strip():
            return []
        query_vector = self.embedding_service.embed_text(query_text)
        embedding_query = (
            self.db.query(PlanRecordChunkEmbedding, PlanRecordChunk)
            .join(PlanRecordChunk, PlanRecordChunk.id == PlanRecordChunkEmbedding.chunk_id)
            .filter(
                PlanRecordChunkEmbedding.provider == self.config.provider,
                PlanRecordChunkEmbedding.model == self.config.model,
                PlanRecordChunkEmbedding.dimension == self.config.dimension,
                PlanRecordChunkEmbedding.status == "completed",
            )
        )
        if record_ids:
            embedding_query = embedding_query.filter(PlanRecordChunk.plan_record_id.in_(record_ids))

        hits: list[SemanticChunkHit] = []
        for embedding, chunk in embedding_query.all():
            score = cosine_similarity(query_vector, [float(value) for value in embedding.vector])
            if score > 0:
                hits.append(SemanticChunkHit(chunk=chunk, score=score))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]
