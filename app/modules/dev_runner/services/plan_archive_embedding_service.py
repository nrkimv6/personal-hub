"""Embedding backfill service for archived plan retrieval chunks."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecordChunk, PlanRecordChunkEmbedding, PlanRecordSearchRun

PLAN_ARCHIVE_EMBEDDING_CONFIG_GROUP = "plan_archive_embedding"
DEFAULT_EMBEDDING_PROVIDER = "local-hash"
DEFAULT_EMBEDDING_MODEL = "hash-bow-v1"
DEFAULT_EMBEDDING_DIMENSION = 32


class EmbeddingProvider(Protocol):
    def embed(self, text: str, config: "PlanArchiveEmbeddingConfig") -> list[float]:
        ...


@dataclass(frozen=True)
class PlanArchiveEmbeddingConfig:
    provider: str = DEFAULT_EMBEDDING_PROVIDER
    model: str = DEFAULT_EMBEDDING_MODEL
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    batch_limit: int = 50
    timeout_seconds: int = 30


class DeterministicHashEmbeddingProvider:
    """Local provider for tests/backfill fallback; no external LLM request."""

    def embed(self, text: str, config: PlanArchiveEmbeddingConfig) -> list[float]:
        vector = [0.0] * config.dimension
        tokens = re.findall(r"[a-zA-Z0-9_./-]+", text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % config.dimension
            vector[idx] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [value / norm for value in vector]


class PlanArchiveEmbeddingService:
    def __init__(
        self,
        db: Session,
        config: PlanArchiveEmbeddingConfig | None = None,
        provider: EmbeddingProvider | None = None,
    ):
        self.db = db
        self.config = config or PlanArchiveEmbeddingConfig()
        self.provider = provider or DeterministicHashEmbeddingProvider()

    @staticmethod
    def resolve_config(
        provider: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        batch_limit: int | None = None,
        timeout_seconds: int | None = None,
    ) -> PlanArchiveEmbeddingConfig:
        resolved_provider = (provider or DEFAULT_EMBEDDING_PROVIDER).strip()
        resolved_model = (model or DEFAULT_EMBEDDING_MODEL).strip()
        if resolved_provider != DEFAULT_EMBEDDING_PROVIDER:
            raise ValueError(f"Unsupported plan archive embedding provider: {resolved_provider}")
        return PlanArchiveEmbeddingConfig(
            provider=resolved_provider,
            model=resolved_model,
            dimension=dimension or DEFAULT_EMBEDDING_DIMENSION,
            batch_limit=batch_limit or 50,
            timeout_seconds=timeout_seconds or 30,
        )

    def embed_text(self, text: str) -> list[float]:
        vector = self.provider.embed(text, self.config)
        if len(vector) != self.config.dimension:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.config.dimension}, got {len(vector)}"
            )
        return [float(value) for value in vector]

    def embed_chunk(self, chunk_id: int, force: bool = False) -> dict:
        chunk = self.db.query(PlanRecordChunk).filter(PlanRecordChunk.id == chunk_id).first()
        if not chunk:
            return {"status": "failed", "chunk_id": chunk_id, "reason": "chunk_not_found"}
        if not chunk.text or not chunk.text.strip():
            return {"status": "skipped", "chunk_id": chunk_id, "reason": "empty_text"}

        existing = (
            self.db.query(PlanRecordChunkEmbedding)
            .filter(
                PlanRecordChunkEmbedding.chunk_id == chunk.id,
                PlanRecordChunkEmbedding.provider == self.config.provider,
                PlanRecordChunkEmbedding.model == self.config.model,
                PlanRecordChunkEmbedding.dimension == self.config.dimension,
                PlanRecordChunkEmbedding.content_hash == chunk.content_hash,
            )
            .first()
        )
        if existing and not force:
            return {"status": "reused", "chunk_id": chunk.id, "embedding_id": existing.id}

        try:
            vector = self.embed_text(chunk.text)
        except Exception as exc:
            run = PlanRecordSearchRun(
                plan_record_id=chunk.plan_record_id,
                run_type="embedding",
                status="failed",
                dry_run=False,
                failed_count=1,
                detail={"chunk_id": chunk.id, "provider": self.config.provider, "model": self.config.model},
                error_message=str(exc),
                started_at=datetime.now(),
                finished_at=datetime.now(),
            )
            self.db.add(run)
            return {"status": "failed", "chunk_id": chunk.id, "reason": str(exc)}

        if existing:
            existing.vector = vector
            existing.status = "completed"
            existing.error_message = None
            existing.updated_at = datetime.now()
            embedding = existing
        else:
            embedding = PlanRecordChunkEmbedding(
                chunk_id=chunk.id,
                plan_record_id=chunk.plan_record_id,
                provider=self.config.provider,
                model=self.config.model,
                dimension=self.config.dimension,
                content_hash=chunk.content_hash,
                vector=vector,
                status="completed",
            )
            self.db.add(embedding)
        self.db.flush()
        return {"status": "created" if not existing else "updated", "chunk_id": chunk.id, "embedding_id": embedding.id}

    def index_embeddings(self, limit: int | None = None, force: bool = False, dry_run: bool = True) -> dict:
        batch_limit = limit or self.config.batch_limit
        chunks = (
            self.db.query(PlanRecordChunk)
            .order_by(PlanRecordChunk.id.asc())
            .limit(batch_limit)
            .all()
        )
        result = {"dry_run": dry_run, "indexed": 0, "failed": 0, "skipped": 0, "errors": []}
        for chunk in chunks:
            if dry_run:
                if not chunk.text or not chunk.text.strip():
                    result["skipped"] += 1
                else:
                    result["indexed"] += 1
                continue
            item = self.embed_chunk(chunk.id, force=force)
            if item["status"] in {"created", "updated", "reused"}:
                result["indexed"] += 1
            elif item["status"] == "skipped":
                result["skipped"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(item.get("reason", "embedding_failed"))
        return result
