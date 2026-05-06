"""Nearest-neighbor clustering helpers for semantic plan archive relations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordChunkEmbedding, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_semantic_search_service import cosine_similarity


class PlanArchiveSemanticClusterService:
    def __init__(self, db: Session):
        self.db = db

    def nearest_plan_pairs(self, threshold: float = 0.75, limit: int = 50) -> list[dict]:
        embeddings = (
            self.db.query(PlanRecordChunkEmbedding)
            .filter(PlanRecordChunkEmbedding.status == "completed")
            .order_by(PlanRecordChunkEmbedding.plan_record_id.asc())
            .all()
        )
        vectors_by_plan: dict[int, list[list[float]]] = defaultdict(list)
        for embedding in embeddings:
            vectors_by_plan[embedding.plan_record_id].append([float(value) for value in embedding.vector])

        records = {
            record.id: record
            for record in self.db.query(PlanRecord)
            .filter(PlanRecord.id.in_(vectors_by_plan.keys()))
            .all()
        }
        pairs: list[dict] = []
        plan_ids = sorted(vectors_by_plan)
        for idx, left_id in enumerate(plan_ids):
            for right_id in plan_ids[idx + 1 :]:
                score = self._plan_similarity(vectors_by_plan[left_id], vectors_by_plan[right_id])
                if score < threshold:
                    continue
                left = records.get(left_id)
                right = records.get(right_id)
                same_context = bool(
                    left
                    and right
                    and (
                        (left.category and left.category == right.category)
                        or bool(set(left.tags or []) & set(right.tags or []))
                    )
                )
                pairs.append(
                    {
                        "source_plan_record_id": left_id,
                        "target_plan_record_id": right_id,
                        "score": score,
                        "same_context": same_context,
                    }
                )
        pairs.sort(key=lambda item: (item["same_context"], item["score"]), reverse=True)
        return pairs[:limit]

    def upsert_semantic_relations(self, threshold: float = 0.75, limit: int = 50, cluster_id: str | None = None) -> dict:
        pairs = self.nearest_plan_pairs(threshold=threshold, limit=limit)
        written = 0
        for pair in pairs:
            relation = (
                self.db.query(PlanRecordRelation)
                .filter(
                    PlanRecordRelation.source_plan_record_id == pair["source_plan_record_id"],
                    PlanRecordRelation.target_plan_record_id == pair["target_plan_record_id"],
                    PlanRecordRelation.relation_type == "semantic_similar",
                )
                .first()
            )
            evidence = {
                "semantic_score": pair["score"],
                "same_context": pair["same_context"],
                "cluster_id": cluster_id,
            }
            score = int(round(pair["score"] * 100))
            if relation:
                relation.score = score
                relation.evidence = evidence
                relation.updated_at = datetime.now()
            else:
                self.db.add(
                    PlanRecordRelation(
                        source_plan_record_id=pair["source_plan_record_id"],
                        target_plan_record_id=pair["target_plan_record_id"],
                        relation_type="semantic_similar",
                        score=score,
                        evidence=evidence,
                    )
                )
            written += 1
        self.db.flush()
        return {"relations": written, "candidates": len(pairs)}

    @staticmethod
    def _plan_similarity(left_vectors: list[list[float]], right_vectors: list[list[float]]) -> float:
        best = 0.0
        for left in left_vectors:
            for right in right_vectors:
                best = max(best, cosine_similarity(left, right))
        return best
