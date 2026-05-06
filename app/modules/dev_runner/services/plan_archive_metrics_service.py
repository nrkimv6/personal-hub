"""Metrics over plan archive retrieval index."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanRecordFileRef, PlanRecordRelation
from app.modules.dev_runner.services.plan_archive_retrieval_service import RetrievalQuery, semantic_cluster_evidence_filter


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
        if query.semantic_cluster_id:
            base = base.join(
                PlanRecordRelation,
                PlanRecordRelation.source_plan_record_id == PlanRecord.id,
            ).filter(
                PlanRecordRelation.relation_type == "semantic_similar",
                semantic_cluster_evidence_filter(query.semantic_cluster_id),
            )
        records = base.all()
        record_ids = [record.id for record in records]

        refs = []
        if record_ids:
            refs_query = self.db.query(PlanRecordFileRef).filter(PlanRecordFileRef.plan_record_id.in_(record_ids))
            if query.path:
                normalized_path = query.path.replace("\\", "/")
                refs_query = refs_query.filter(PlanRecordFileRef.path.ilike(f"%{normalized_path}%"))
            if query.repo_key:
                refs_query = refs_query.filter(PlanRecordFileRef.repo_key == query.repo_key)
            refs = refs_query.all()

        refs_by_record: dict[int, set[str]] = defaultdict(set)
        repo_keys_by_record: dict[int, set[str]] = defaultdict(set)
        for ref in refs:
            refs_by_record[ref.plan_record_id].add(ref.module or ref.path)
            repo_keys_by_record[ref.plan_record_id].add(ref.repo_key or "monitor-page")

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

        path_counter: Counter[tuple[str, str]] = Counter()
        mentioned_counter: Counter[tuple[str, str]] = Counter()
        changed_counter: Counter[tuple[str, str]] = Counter()
        module_changed: dict[str, set[str]] = defaultdict(set)
        module_mentioned: dict[str, set[str]] = defaultdict(set)
        repo_counter: Counter[str] = Counter()
        cross_repo_record_ids: set[int] = set()
        downstream_sync_paths: set[tuple[str, str]] = set()
        for ref in refs:
            repo_key = ref.repo_key or "monitor-page"
            path_key = (repo_key, ref.path)
            path_counter[path_key] += 1
            repo_counter[repo_key] += 1
            if repo_key != "monitor-page":
                cross_repo_record_ids.add(ref.plan_record_id)
            if ref.source_type == "mentioned_in_plan":
                mentioned_counter[path_key] += 1
                module_mentioned[ref.module or "unknown"].add(ref.path)
            if ref.source_type in {"git_changed", "downstream_sync"}:
                changed_counter[path_key] += 1
                module_changed[ref.module or "unknown"].add(ref.path)
            if ref.source_type == "downstream_sync":
                downstream_sync_paths.add(path_key)

        top_file_refs = [
            {
                "path": path,
                "repo_key": repo_key,
                "count": count,
                "mentioned_count": mentioned_counter[(repo_key, path)],
                "changed_count": changed_counter[(repo_key, path)],
            }
            for (repo_key, path), count in path_counter.most_common(10)
        ]

        missing_file_candidates = []
        for module, changed_paths in module_changed.items():
            missing = sorted(changed_paths - module_mentioned.get(module, set()))
            if missing:
                missing_file_candidates.append({"module": module, "count": len(missing), "paths": missing[:10]})
        missing_file_candidates.sort(key=lambda item: item["count"], reverse=True)
        downstream_sync_missing_candidates = [
            {
                "repo_key": repo_key,
                "path": path,
                "count": changed_counter[(repo_key, path)],
            }
            for (repo_key, path), count in changed_counter.items()
            if repo_key != "monitor-page" and (repo_key, path) not in downstream_sync_paths
        ]
        downstream_sync_missing_candidates.sort(key=lambda item: item["count"], reverse=True)

        relation_query = self.db.query(
            PlanRecordRelation.relation_type,
            func.count(PlanRecordRelation.id),
        )
        if record_ids:
            relation_query = relation_query.filter(PlanRecordRelation.source_plan_record_id.in_(record_ids))
        else:
            relation_query = relation_query.filter(False)
        if query.semantic_cluster_id:
            relation_query = relation_query.filter(
                PlanRecordRelation.relation_type == "semantic_similar",
                semantic_cluster_evidence_filter(query.semantic_cluster_id),
            )
        relation_counts = {
            relation_type: count
            for relation_type, count in relation_query.group_by(PlanRecordRelation.relation_type).all()
        }

        chain_depth_max = self.db.query(func.max(PlanRecord.recurrence_count)).scalar() or 0

        return {
            "total_plans": len(records),
            "followup_rates": followup_rates,
            "top_file_refs": top_file_refs,
            "missing_file_candidates": missing_file_candidates[:10],
            "relation_counts": relation_counts,
            "chain_depth_max": chain_depth_max,
            "repo_counts": dict(repo_counter),
            "cross_repo_plan_count": len(cross_repo_record_ids),
            "multi_repo_plan_count": sum(1 for keys in repo_keys_by_record.values() if len(keys) > 1),
            "downstream_sync_missing_candidates": downstream_sync_missing_candidates[:10],
        }
