from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordChunkEmbedding,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.services.plan_archive_embedding_service import (
    PlanArchiveEmbeddingConfig,
    PlanArchiveEmbeddingService,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordChunkEmbedding.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_chunk(db, text="semantic retrieval evidence", content_hash="hash-a"):
    record = PlanRecord(
        filename_hash=f"record-{content_hash}",
        file_path=f"docs/archive/{content_hash}.md",
        title="Embedding",
        archived_at=datetime.now(),
        status="archived",
    )
    db.add(record)
    db.flush()
    chunk = PlanRecordChunk(
        plan_record_id=record.id,
        chunk_index=0,
        section_type="body",
        heading="Body",
        text=text,
        content_hash=content_hash,
        token_estimate=3,
    )
    db.add(chunk)
    db.flush()
    return record, chunk


class FixedProvider:
    def __init__(self, vector):
        self.vector = vector

    def embed(self, text, config):
        return self.vector


class FailingProvider:
    def embed(self, text, config):
        raise RuntimeError("provider unavailable")


def test_embed_chunk_right_creates_embedding():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunk(db)
        result = PlanArchiveEmbeddingService(db).embed_chunk(chunk.id)
        assert result["status"] == "created"
        saved = db.query(PlanRecordChunkEmbedding).one()
        assert saved.chunk_id == chunk.id
        assert saved.provider == "local-hash"
        assert len(saved.vector) == 32
    finally:
        db.close()
        engine.dispose()


def test_embed_chunk_boundary_empty_text_skips_with_reason():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunk(db, text="   ")
        result = PlanArchiveEmbeddingService(db).embed_chunk(chunk.id)
        assert result == {"status": "skipped", "chunk_id": chunk.id, "reason": "empty_text"}
        assert db.query(PlanRecordChunkEmbedding).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_embed_chunk_reference_reuses_same_content_hash():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunk(db)
        svc = PlanArchiveEmbeddingService(db)
        first = svc.embed_chunk(chunk.id)
        second = svc.embed_chunk(chunk.id)
        assert first["status"] == "created"
        assert second["status"] == "reused"
        assert db.query(PlanRecordChunkEmbedding).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_embed_chunk_error_rejects_dimension_mismatch():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunk(db)
        config = PlanArchiveEmbeddingConfig(dimension=3)
        svc = PlanArchiveEmbeddingService(db, config=config, provider=FixedProvider([1.0, 0.0]))
        result = svc.embed_chunk(chunk.id)
        assert result["status"] == "failed"
        assert "dimension mismatch" in result["reason"]
        assert db.query(PlanRecordChunkEmbedding).count() == 0
        assert db.query(PlanRecordSearchRun).one().status == "failed"
    finally:
        db.close()
        engine.dispose()


def test_embed_chunk_error_preserves_chunk():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunk(db)
        result = PlanArchiveEmbeddingService(db, provider=FailingProvider()).embed_chunk(chunk.id)
        assert result["status"] == "failed"
        assert db.query(PlanRecordChunk).filter_by(id=chunk.id).one()
        assert db.query(PlanRecordChunkEmbedding).count() == 0
    finally:
        db.close()
        engine.dispose()
