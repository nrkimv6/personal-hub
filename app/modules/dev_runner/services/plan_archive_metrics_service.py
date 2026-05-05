"""Metrics over plan archive retrieval index."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordFileRef, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_retrieval_service import RetrievalQuery


class PlanArchiveMetricsService:
    def __init__(self, db: Session):
        self.db = db

    def calculate(self, query: RetrievalQuery) -> dict:
        base = self.db.query(PlanRecord).filter(PlanRecord.archived_at.isnot(None))
        if query.category:
            base = base.filter(PlanRecord.category == query.category)
        if query.date_from:
            base = base.filter(PlanRecord.archived_at >= query.date_from)
        if query.date_to:
            base = base.filter(PlanRecord.archived_at <= query.date_to)
        records = base.all()
        record_ids = [record.id for record in records]

        refs = []
        if record_ids:
            refs_query = self.db.query(PlanRecordFileRef).filter(PlanRecordFileRef.plan_record_id.in_(record_ids))
            if query.path:
                normalized_path = query.path.replace("\\", "/")
                refs_query = refs_query.filter(PlanRecordFileRef.path.ilike(f"%{normalized_path}%"))
            refs = refs_query.all()

        refs_by_record: dict[int, set[str]] = defaultdict(set)
        for ref in refs:
            refs_by_record[ref.plan_record_id].add(ref.module or ref.path)

        followup_rates = {}
        for days in (7, 14, 30):
            matched = 0
            for record in records:
                if not record.archived_at:
                    continue
                window_end = record.archived_at + timedelta(days=days)
                candidate = (
                    self.db.query(PlanRecord)
                    .filter(
                        PlanRecord.id != record.id,
                        PlanRecord.archived_at > record.archived_at,
                        PlanRecord.archived_at <= window_end,
                    )
                )
                if record.category:
                    candidate = candidate.filter(PlanRecord.category == record.category)
                next_records = candidate.all()
                if not next_records:
                    continue
                current_refs = refs_by_record.get(record.id, set())
                if not current_refs:
                    matched += 1
                    continue
                next_ids = [item.id for item in next_records]
                overlap = (
                    self.db.query(PlanRecordFileRef)
                    .filter(PlanRecordFileRef.plan_record_id.in_(next_ids))
                    .filter(PlanRecordFileRef.module.in_(current_refs))
                    .first()
                )
                if overlap:
                    matched += 1
            followup_rates[f"days_{days}"] = (matched / len(records)) if records else 0

        path_counter: Counter[str] = Counter()
        mentioned_counter: Counter[str] = Counter()
        changed_counter: Counter[str] = Counter()
        module_changed: dict[str, set[str]] = defaultdict(set)
        module_mentioned: dict[str, set[str]] = defaultdict(set)
        for ref in refs:
            path_counter[ref.path] += 1
            if ref.source_type == "mentioned_in_plan":
                mentioned_counter[ref.path] += 1
                module_mentioned[ref.module or "unknown"].add(ref.path)
            if ref.source_type == "git_changed":
                changed_counter[ref.path] += 1
                module_changed[ref.module or "unknown"].add(ref.path)

        top_file_refs = [
            {
                "path": path,
                "count": count,
                "mentioned_count": mentioned_counter[path],
                "changed_count": changed_counter[path],
            }
            for path, count in path_counter.most_common(10)
        ]

        missing_file_candidates = []
        for module, changed_paths in module_changed.items():
            missing = sorted(changed_paths - module_mentioned.get(module, set()))
            if missing:
                missing_file_candidates.append({"module": module, "count": len(missing), "paths": missing[:10]})
        missing_file_candidates.sort(key=lambda item: item["count"], reverse=True)

        relation_counts = {
            relation_type: count
            for relation_type, count in self.db.query(
                PlanRecordRelation.relation_type,
                func.count(PlanRecordRelation.id),
            ).group_by(PlanRecordRelation.relation_type).all()
        }

        chain_depth_max = self.db.query(func.max(PlanRecord.recurrence_count)).scalar() or 0

        return {
            "total_plans": len(records),
            "followup_rates": followup_rates,
            "top_file_refs": top_file_refs,
            "missing_file_candidates": missing_file_candidates[:10],
            "relation_counts": relation_counts,
            "chain_depth_max": chain_depth_max,
        }
