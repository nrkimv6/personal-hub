"""Review workflow for Plan Archive insight reports."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models.plan_archive_insight import PlanArchiveInsightReport
from app.models.plan_record import PlanRecord, PlanRecordChunk, PlanRecordFileRef

VALID_REVIEW_STATUSES = {"unreviewed", "reviewing", "accepted", "rejected", "promoted"}
ALLOWED_TRANSITIONS = {
    "unreviewed": {"reviewing", "accepted", "rejected"},
    "reviewing": {"unreviewed", "accepted", "rejected"},
    "accepted": {"reviewing", "promoted", "rejected"},
    "rejected": {"reviewing"},
    "promoted": {"reviewing"},
}


class PlanArchiveInsightReviewService:
    def __init__(self, db: Session, plans_dir: Path | None = None):
        self.db = db
        self.plans_dir = plans_dir or PROJECT_ROOT / ".worktrees" / "plans" / "docs" / "plan"

    def list_reports(
        self,
        *,
        status: str | None = None,
        review_status: str | None = None,
        grouping: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        query = self.db.query(PlanArchiveInsightReport)
        if status:
            query = query.filter(PlanArchiveInsightReport.status == status)
        if review_status:
            query = query.filter(PlanArchiveInsightReport.review_status == review_status)
        if grouping:
            query = query.filter(PlanArchiveInsightReport.grouping == grouping)
        total = query.count()
        reports = (
            query.order_by(PlanArchiveInsightReport.created_at.desc(), PlanArchiveInsightReport.id.desc())
            .offset(max(0, skip))
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return {"items": [self.serialize_report(report) for report in reports], "total": total}

    def get_report(self, report_id: int) -> PlanArchiveInsightReport | None:
        return self.db.query(PlanArchiveInsightReport).filter_by(id=report_id).first()

    def get_detail(self, report_id: int) -> dict[str, Any] | None:
        report = self.get_report(report_id)
        if not report:
            return None
        return self.serialize_report(report, include_detail=True)

    def update_review(self, report_id: int, review_status: str, review_note: str | None = None) -> dict[str, Any]:
        if review_status not in VALID_REVIEW_STATUSES:
            raise ValueError("INVALID_REVIEW_STATUS")
        report = self.get_report(report_id)
        if not report:
            raise LookupError("REPORT_NOT_FOUND")
        current = report.review_status or "unreviewed"
        if review_status != current and review_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError("INVALID_REVIEW_TRANSITION")
        report.review_status = review_status
        report.review_note = review_note
        self.db.commit()
        self.db.refresh(report)
        return self.serialize_report(report, include_detail=True)

    def get_evidence_source(self, report_id: int, source_type: str, source_id: int) -> dict[str, Any] | None:
        if not self.get_report(report_id):
            return None
        if source_type == "record":
            record = self.db.query(PlanRecord).filter_by(id=source_id).first()
            return {"type": "record", "record": self._serialize_record(record)} if record else None
        if source_type == "chunk":
            chunk = self.db.query(PlanRecordChunk).filter_by(id=source_id).first()
            if not chunk:
                return None
            return {
                "type": "chunk",
                "chunk": {
                    "id": chunk.id,
                    "record_id": chunk.plan_record_id,
                    "heading": chunk.heading,
                    "section_type": chunk.section_type,
                    "text": chunk.text,
                },
                "record": self._serialize_record(chunk.record) if getattr(chunk, "record", None) else None,
            }
        if source_type == "file_ref":
            ref = self.db.query(PlanRecordFileRef).filter_by(id=source_id).first()
            if not ref:
                return None
            return {
                "type": "file_ref",
                "file_ref": {
                    "id": ref.id,
                    "record_id": ref.plan_record_id,
                    "path": ref.path,
                    "source_type": ref.source_type,
                    "module": ref.module,
                    "commit_sha": ref.commit_sha,
                },
                "record": self._serialize_record(ref.record) if getattr(ref, "record", None) else None,
            }
        raise ValueError("INVALID_SOURCE_TYPE")

    def promote_plan_candidate(
        self,
        report_id: int,
        candidate_index: int,
        *,
        confirm: bool = False,
        title: str | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise ValueError("CONFIRM_REQUIRED")
        report = self.get_report(report_id)
        if not report:
            raise LookupError("REPORT_NOT_FOUND")
        candidates = (report.insight_json or {}).get("suggested_plan_candidates") or []
        if candidate_index < 0 or candidate_index >= len(candidates):
            raise ValueError("CANDIDATE_NOT_FOUND")
        candidate = candidates[candidate_index]
        plan_title = title or candidate.get("title") or f"Plan Archive insight follow-up {report.id}"
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        filename = self._draft_filename(plan_title)
        path = self.plans_dir / filename
        if path.exists():
            raise FileExistsError("DUPLICATE_CANDIDATE")
        path.write_text(self._draft_content(report, candidate, plan_title), encoding="utf-8")
        report.review_status = "promoted"
        report.promoted_plan_path = str(path)
        self.db.commit()
        return {"path": str(path), "report": self.serialize_report(report, include_detail=True)}

    def serialize_report(self, report: PlanArchiveInsightReport, include_detail: bool = False) -> dict[str, Any]:
        insight = report.insight_json or {}
        data = {
            "id": report.id,
            "range_start": report.range_start,
            "range_end": report.range_end,
            "grouping": report.grouping,
            "metrics_hash": report.metrics_hash,
            "provider": report.provider,
            "model": report.model,
            "status": report.status,
            "review_status": report.review_status,
            "review_note": report.review_note,
            "promoted_plan_path": report.promoted_plan_path,
            "warning": report.warning,
            "error_message": report.error_message,
            "llm_request_id": report.llm_request_id,
            "created_at": report.created_at,
            "completed_at": report.completed_at,
            "summary": insight.get("summary"),
            "root_causes": insight.get("root_causes") or [],
            "recommendations": insight.get("recommendations") or [],
            "suggested_plan_candidates": insight.get("suggested_plan_candidates") or [],
        }
        if include_detail:
            data.update(
                {
                    "metrics": report.metrics_json or {},
                    "evidence": report.evidence_json or [],
                    "insight": insight,
                    "raw_response": report.raw_response,
                }
            )
        return data

    @staticmethod
    def _serialize_record(record: PlanRecord | None) -> dict[str, Any] | None:
        if not record:
            return None
        return {
            "id": record.id,
            "filename_hash": record.filename_hash,
            "file_path": record.file_path,
            "title": record.title,
            "status": record.status,
            "category": record.category,
            "summary": record.summary,
            "archived_at": record.archived_at,
        }

    @staticmethod
    def _draft_filename(title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", title.strip()).strip("-").lower()
        slug = slug[:80] or "plan-archive-insight-follow-up"
        return f"{datetime.now():%Y-%m-%d}_draft-{slug}.md"

    @staticmethod
    def _draft_content(report: PlanArchiveInsightReport, candidate: dict[str, Any], title: str) -> str:
        evidence_ids = candidate.get("evidence_ids") or []
        return f"""# {title}

> 작성일시: {datetime.now():%Y-%m-%d %H:%M}
> 기준 insight report: {report.id}
> 상태: 초안
> 진행률: 0/0 (0%)
> 요약: {candidate.get("reason") or "Plan Archive insight에서 승격된 후속 계획 후보"}

---

## 개요

{candidate.get("reason") or "후속 검토가 필요합니다."}

## Evidence

{chr(10).join(f"- {item}" for item in evidence_ids) if evidence_ids else "- source 없음: 수동 확인 필요"}
"""
