from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordChunkEmbedding, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_semantic_cluster_service import PlanArchiveSemanticClusterService


def _make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for table in (
        PlanRecord.__table__,
        PlanRecordChunk.__table__,
        PlanRecordChunkEmbedding.__table__,
        PlanRecordRelation.__table__,
    ):
        table.create(bind=engine, checkfirst=True)
    return sessionmaker(bind=engine)(), engine


def _add_plan(db, filename_hash, category, vector):
    record = PlanRecord(
        filename_hash=filename_hash,
        file_path=f"docs/archive/{filename_hash}.md",
        category=category,
        tags=["feat"],
        archived_at=datetime.now(),
        status="archived",
    )
    db.add(record)
    db.flush()
    chunk = PlanRecordChunk(
        plan_record_id=record.id,
        chunk_index=0,
        section_type="body",
        text=filename_hash,
        content_hash=f"{filename_hash}-hash",
        token_estimate=1,
    )
    db.add(chunk)
    db.flush()
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
    db.flush()
    return record


def test_semantic_cluster_right_groups_related_plans():
    db, engine = _make_session()
    try:
        left = _add_plan(db, "left", "infra", [1.0, 0.0, 0.0])
        right = _add_plan(db, "right", "infra", [0.95, 0.05, 0.0])
        _add_plan(db, "far", "infra", [0.0, 1.0, 0.0])
        result = PlanArchiveSemanticClusterService(db).upsert_semantic_relations(threshold=0.9, cluster_id="c1")
        assert result["relations"] == 1
        relation = db.query(PlanRecordRelation).one()
        assert relation.source_plan_record_id == left.id
        assert relation.target_plan_record_id == right.id
        assert relation.relation_type == "semantic_similar"
        assert relation.evidence["cluster_id"] == "c1"
    finally:
        db.close()
        engine.dispose()
