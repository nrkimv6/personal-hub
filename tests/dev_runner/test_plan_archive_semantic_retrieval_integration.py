from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import (
    PlanRecord,
    PlanRecordChunk,
    PlanRecordChunkEmbedding,
    PlanRecordFileRef,
    PlanRecordRelation,
    PlanRecordSearchRun,
)
from app.modules.dev_runner.services.plan_archive_embedding_service import (
    PlanArchiveEmbeddingConfig,
    PlanArchiveEmbeddingService,
)
from app.modules.dev_runner.services.plan_archive_retrieval_service import PlanArchiveRetrievalService, RetrievalQuery
from app.modules.dev_runner.services.plan_archive_semantic_cluster_service import PlanArchiveSemanticClusterService


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordChunkEmbedding.__table__,
        PlanRecordFileRef.__table__,
        PlanRecordRelation.__table__,
        PlanRecordSearchRun.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_chunked_plan(db, filename_hash, text, path=None):
    record = PlanRecord(
        filename_hash=filename_hash,
        file_path=f"docs/archive/{filename_hash}.md",
        title=filename_hash,
        category="infra",
        tags=["feat"],
        archived_at=datetime.now(),
        status="archived",
    )
    db.add(record)
    db.flush()
    chunk = PlanRecordChunk(
        plan_record_id=record.id,
        chunk_index=0,
        section_type="todo",
        heading="TODO",
        text=text,
        content_hash=f"{filename_hash}-hash",
        token_estimate=5,
    )
    db.add(chunk)
    db.flush()
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


class SharedIntentProvider:
    def embed(self, text, config):
        lowered = text.lower()
        if "dry-run" in lowered or "preview" in lowered:
            return [1.0, 0.0, 0.0]
        if "provider failure" in lowered:
            raise RuntimeError("provider failure")
        return [0.0, 1.0, 0.0]


def test_semantic_retrieval_integration_backfill_then_search():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunked_plan(db, "dry-run-plan", "dry-run apply execution safeguards")
        config = PlanArchiveEmbeddingConfig(dimension=3)
        PlanArchiveEmbeddingService(db, config=config, provider=SharedIntentProvider()).embed_chunk(chunk.id)
        from app.modules.dev_runner.services import plan_archive_retrieval_service as retrieval_module

        original = retrieval_module.PlanArchiveSemanticSearchService

        class InjectedSemanticSearch:
            def __init__(self, db):
                from app.modules.dev_runner.services.plan_archive_semantic_search_service import PlanArchiveSemanticSearchService

                service = PlanArchiveEmbeddingService(db, config=config, provider=SharedIntentProvider())
                self.inner = PlanArchiveSemanticSearchService(db, embedding_service=service)

            def search_chunks(self, *args, **kwargs):
                return self.inner.search_chunks(*args, **kwargs)

        retrieval_module.PlanArchiveSemanticSearchService = InjectedSemanticSearch
        try:
            result = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="preview execution", limit=5))
        finally:
            retrieval_module.PlanArchiveSemanticSearchService = original
        assert result["total"] == 1
        assert result["results"][0]["plan"].filename_hash == "dry-run-plan"
    finally:
        db.close()
        engine.dispose()


def test_semantic_retrieval_integration_groups_dry_run_apply_plans():
    db, engine = _make_session()
    try:
        _left, left_chunk = _add_chunked_plan(db, "dry-run", "dry-run safety")
        _right, right_chunk = _add_chunked_plan(db, "preview", "preview apply safety")
        config = PlanArchiveEmbeddingConfig(dimension=3)
        svc = PlanArchiveEmbeddingService(db, config=config, provider=SharedIntentProvider())
        svc.embed_chunk(left_chunk.id)
        svc.embed_chunk(right_chunk.id)
        result = PlanArchiveSemanticClusterService(db).upsert_semantic_relations(threshold=0.9, cluster_id="dryrun-apply")
        assert result["relations"] == 1
        assert db.query(PlanRecordRelation).filter_by(relation_type="semantic_similar").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_semantic_retrieval_integration_provider_failure_keeps_fts_fallback():
    db, engine = _make_session()
    try:
        _record, chunk = _add_chunked_plan(db, "fallback", "lexical fallback survives provider failure")
        result = PlanArchiveEmbeddingService(db, provider=SharedIntentProvider()).embed_chunk(chunk.id)
        assert result["status"] == "failed"
        search = PlanArchiveRetrievalService(db).search(RetrievalQuery(q="fallback", limit=5))
        assert search["total"] == 1
        assert search["results"][0]["score_detail"]["lexical"] > 0
    finally:
        db.close()
        engine.dispose()
