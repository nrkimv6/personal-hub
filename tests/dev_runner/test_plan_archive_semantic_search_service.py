from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordChunkEmbedding,
    PlanRecordFileRef,
    PlanRecordRelation,
)
from app.modules.dev_runner.services.plan_archive_embedding_service import PlanArchiveEmbeddingConfig, PlanArchiveEmbeddingService
from app.modules.dev_runner.services.plan_archive_retrieval_service import PlanArchiveRetrievalService, RetrievalQuery


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordChunkEmbedding.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_record(db, filename_hash, text, vector=None, path=None):
    record = PlanRecord(
        filename_hash=filename_hash,
        file_path=f"docs/archive/{filename_hash}.md",
        title=filename_hash,
        archived_at=datetime.now(),
        status="archived",
    )
    db.add(record)
    db.flush()
    chunk = PlanRecordChunk(
        plan_record_id=record.id,
        chunk_index=0,
        section_type="body",
        text=text,
        content_hash=f"{filename_hash}-hash",
        token_estimate=5,
    )
    db.add(chunk)
    db.flush()
    if vector:
        db.add(
            PlanRecordChunkEmbedding(
                chunk_id=chunk.id,
                plan_record_id=record.id,
                provider="local-hash",
                model="hash-bow-v1",
                dimension=len(vector),
                content_hash=chunk.content_hash,
                vector=vector,
            )
        )
    if path:
        db.add(
            PlanRecordFileRef(
                plan_record_id=record.id,
                source_type="mentioned_in_plan",
                path=path,
                module="app",
            )
        )
    db.flush()
    return record, chunk


class QueryProvider:
    def embed(self, text, config):
        if "paraphrase" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


def test_semantic_search_right_finds_paraphrase():
    db, engine = _make_session()
    try:
        _add_record(db, "semantic-hit", "dry-run apply workflow", vector=[1.0, 0.0, 0.0])
        svc = PlanArchiveRetrievalService(db)
        semantic = PlanArchiveEmbeddingService(db, config=PlanArchiveEmbeddingConfig(dimension=3), provider=QueryProvider())
        from app.modules.dev_runner.services import plan_archive_retrieval_service as retrieval_module

        original = retrieval_module.PlanArchiveSemanticSearchService

        class InjectedSemanticSearch:
            def __init__(self, db):
                from app.modules.dev_runner.services.plan_archive_semantic_search_service import PlanArchiveSemanticSearchService

                self.inner = PlanArchiveSemanticSearchService(db, embedding_service=semantic)

            def search_chunks(self, *args, **kwargs):
                return self.inner.search_chunks(*args, **kwargs)

        retrieval_module.PlanArchiveSemanticSearchService = InjectedSemanticSearch
        try:
            result = svc.search(RetrievalQuery(q="paraphrase request", limit=5))
        finally:
            retrieval_module.PlanArchiveSemanticSearchService = original
        assert result["total"] == 1
        assert result["results"][0]["score_detail"]["semantic"] > 0
    finally:
        db.close()
        engine.dispose()


def test_semantic_search_boundary_missing_embedding_uses_lexical_fallback():
    db, engine = _make_session()
    try:
        _add_record(db, "lexical-hit", "lexical fallback evidence")
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="fallback", limit=5))
        assert result["total"] == 1
        assert result["results"][0]["score_detail"]["lexical"] > 0
        assert result["results"][0]["score_detail"]["semantic"] == 0
    finally:
        db.close()
        engine.dispose()


def test_exact_path_query_prioritizes_file_score_compliance():
    db, engine = _make_session()
    try:
        _add_record(db, "semantic-only", "app/models/plan_record.py mention", vector=[1.0, 0.0, 0.0])
        _add_record(db, "file-hit", "unrelated body", path="app/models/plan_record.py")
        result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="app/models/plan_record.py", limit=5))
        assert result["total"] == 1
        assert result["results"][0]["plan"].filename_hash == "file-hit"
        assert result["results"][0]["score_detail"]["file"] >= 100
    finally:
        db.close()
        engine.dispose()
