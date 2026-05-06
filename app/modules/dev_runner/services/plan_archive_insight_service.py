"""Plan Archive insight batch prompt and queue service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.dev_runner.services.plan_archive_context_service import PlanArchiveContextService
from app.modules.dev_runner.services.plan_archive_metrics_service import PlanArchiveMetricsService
from app.modules.dev_runner.services.plan_archive_retrieval_service import PlanArchiveRetrievalService, RetrievalQuery

CALLER_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH = "plan_archive_insight_batch"


@dataclass(frozen=True)
class PlanArchiveInsightBatchQuery:
    date_from: datetime | None = None
    date_to: datetime | None = None
    grouping: str = "category"
    category: str | None = None
    path: str | None = None
    limit: int = 20
    token_budget: int = 3000


class PlanArchiveInsightService:
    def __init__(self, db: Session):
        self.db = db

    def build_payload(self, query: PlanArchiveInsightBatchQuery) -> dict[str, Any]:
        retrieval_query = RetrievalQuery(
            date_from=query.date_from,
            date_to=query.date_to,
            category=query.category,
            path=query.path,
            limit=query.limit,
        )
        metrics = PlanArchiveMetricsService(self.db).calculate(retrieval_query)
        retrieval = PlanArchiveRetrievalService(self.db).search(retrieval_query)
        context = PlanArchiveContextService().assemble(
            retrieval,
            token_budget=query.token_budget,
            include_raw=False,
        )
        evidence = self._sample_evidence(context.get("evidence", []), query.token_budget)
        warnings = []
        if not evidence:
            warnings.append("EMPTY_EVIDENCE")
        return {
            "range": {
                "start": query.date_from.isoformat() if query.date_from else None,
                "end": query.date_to.isoformat() if query.date_to else None,
            },
            "grouping": query.grouping,
            "filters": {
                "category": query.category,
                "path": query.path,
                "limit": query.limit,
            },
            "metrics": metrics,
            "evidence": evidence,
            "context_metrics": context.get("metrics", {}),
            "warnings": warnings,
        }

    def build_prompt(self, payload: dict[str, Any]) -> str:
        compact = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return f"""Analyze the following deterministic Plan Archive metrics and evidence.

Rules:
- Use only the provided metrics and evidence.
- Do not infer from raw archived plan bodies.
- Return JSON only.

Input JSON:
{compact}

Output JSON schema:
{{
  "summary": "2-4 sentence summary of the period",
  "root_causes": ["recurring root cause"],
  "missed_dimensions": ["file/module/test/UX dimension that seems repeatedly missed"],
  "recommendations": ["specific recommendation"],
  "suggested_plan_candidates": [
    {{"title": "candidate plan title", "reason": "why it is warranted", "evidence_ids": ["record/chunk/file ids"]}}
  ]
}}"""

    def metrics_hash(self, payload: dict[str, Any]) -> str:
        source = {
            "range": payload.get("range"),
            "grouping": payload.get("grouping"),
            "filters": payload.get("filters"),
            "metrics": payload.get("metrics"),
            "evidence": payload.get("evidence"),
        }
        encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def preview_or_enqueue(
        self,
        query: PlanArchiveInsightBatchQuery,
        *,
        apply: bool = False,
        force: bool = False,
        provider: str | None = None,
        model: str | None = None,
        requested_by: str = "api",
    ) -> dict[str, Any]:
        payload = self.build_payload(query)
        prompt = self.build_prompt(payload)
        metrics_hash = self.metrics_hash(payload)
        resolved_provider, resolved_model = LLMService(self.db).resolve_provider_model(
            CALLER_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH,
            provider=provider,
            model=model,
        )

        base_response = {
            "dry_run": not apply,
            "queued": False,
            "skipped": False,
            "reason": None,
            "report_id": None,
            "llm_request_id": None,
            "provider": resolved_provider,
            "model": resolved_model,
            "metrics_hash": metrics_hash,
            "metrics": payload["metrics"],
            "evidence": payload["evidence"],
            "prompt": prompt,
            "warnings": payload["warnings"],
        }

        if not apply:
            return base_response
        if payload["metrics"].get("total_plans", 0) <= 0:
            return {**base_response, "skipped": True, "reason": "EMPTY_METRICS"}

        existing_active = self._find_existing_active(query, resolved_provider, resolved_model)
        if existing_active and not force:
            return {
                **base_response,
                "skipped": True,
                "reason": "DUPLICATE_ACTIVE_REQUEST",
                "report_id": existing_active.id,
                "llm_request_id": existing_active.llm_request_id,
            }

        existing_completed = self._find_existing_completed(query, resolved_provider, resolved_model, metrics_hash)
        if existing_completed and not force:
            return {
                **base_response,
                "skipped": True,
                "reason": "REUSED_COMPLETED_REPORT",
                "report_id": existing_completed.id,
                "llm_request_id": existing_completed.llm_request_id,
            }

        report = PlanArchiveInsightReport(
            range_start=query.date_from,
            range_end=query.date_to,
            grouping=query.grouping,
            metrics_hash=metrics_hash,
            metrics_json=payload["metrics"],
            evidence_json=payload["evidence"],
            provider=resolved_provider,
            model=resolved_model,
            status="pending",
            warning=";".join(payload["warnings"]) if payload["warnings"] else None,
        )
        self.db.add(report)
        self.db.flush()
        llm_request = LLMRequest(
            caller_type=CALLER_TYPE_PLAN_ARCHIVE_INSIGHT_BATCH,
            caller_id=str(report.id),
            prompt=prompt,
            requested_by=requested_by,
            request_source="plan_archive_insight_batch",
            provider=resolved_provider,
            model=resolved_model,
            queue_name="utility",
            cli_options=json.dumps({"parse_json": True}, ensure_ascii=False),
        )
        self.db.add(llm_request)
        self.db.flush()
        report.llm_request_id = llm_request.id
        self.db.commit()
        return {
            **base_response,
            "queued": True,
            "report_id": report.id,
            "llm_request_id": llm_request.id,
        }

    def _find_existing_active(
        self,
        query: PlanArchiveInsightBatchQuery,
        provider: str,
        model: str,
    ) -> PlanArchiveInsightReport | None:
        return (
            self.db.query(PlanArchiveInsightReport)
            .filter(
                PlanArchiveInsightReport.range_start == query.date_from,
                PlanArchiveInsightReport.range_end == query.date_to,
                PlanArchiveInsightReport.grouping == query.grouping,
                PlanArchiveInsightReport.provider == provider,
                PlanArchiveInsightReport.model == model,
                PlanArchiveInsightReport.status.in_(["pending", "processing"]),
            )
            .order_by(PlanArchiveInsightReport.created_at.desc())
            .first()
        )

    def _find_existing_completed(
        self,
        query: PlanArchiveInsightBatchQuery,
        provider: str,
        model: str,
        metrics_hash: str,
    ) -> PlanArchiveInsightReport | None:
        return (
            self.db.query(PlanArchiveInsightReport)
            .filter(
                PlanArchiveInsightReport.range_start == query.date_from,
                PlanArchiveInsightReport.range_end == query.date_to,
                PlanArchiveInsightReport.grouping == query.grouping,
                PlanArchiveInsightReport.provider == provider,
                PlanArchiveInsightReport.model == model,
                PlanArchiveInsightReport.metrics_hash == metrics_hash,
                PlanArchiveInsightReport.status == "completed",
            )
            .order_by(PlanArchiveInsightReport.completed_at.desc())
            .first()
        )

    @staticmethod
    def _sample_evidence(evidence: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
        budget = max(200, token_budget)
        sampled = []
        used = 0
        for item in evidence:
            text = item.get("text") or item.get("path") or ""
            estimate = max(1, len(str(text).split()))
            if used + estimate > budget:
                break
            sampled.append(item)
            used += estimate
        return sampled
