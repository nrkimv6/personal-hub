"""Result persistence for plan_archive_insight_batch LLM requests."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import is_connection_error
from app.models.plan_archive_insight import PlanArchiveInsightReport

logger = logging.getLogger(__name__)


def _normalize_result_payload(result: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    raw_response = result.get("raw_response") or ""
    payload = result.get("result")
    if isinstance(payload, dict):
        return payload, raw_response
    if isinstance(payload, str) and payload.strip():
        try:
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded, raw_response
        except Exception:
            raw_response = raw_response or payload
    if raw_response.strip():
        try:
            decoded = json.loads(raw_response)
            if isinstance(decoded, dict):
                return decoded, raw_response
        except Exception:
            pass
    return None, raw_response


def save_plan_archive_insight_result(db: Session, request, result: dict[str, Any]) -> bool:
    """Persist plan_archive_insight_batch output into its report row."""
    try:
        report = None
        if getattr(request, "caller_id", None):
            try:
                report = db.query(PlanArchiveInsightReport).filter_by(id=int(request.caller_id)).first()
            except (TypeError, ValueError):
                report = None
        if report is None:
            report = db.query(PlanArchiveInsightReport).filter_by(llm_request_id=request.id).first()
        if report is None:
            logger.error("save_plan_archive_insight_result: report not found for request=%s", request.id)
            return False

        payload, raw_response = _normalize_result_payload(result)
        now = datetime.now()
        report.raw_response = raw_response
        report.completed_at = now
        if payload is None:
            report.status = "failed"
            report.error_message = "INVALID_JSON_RESPONSE"
            db.commit()
            return False

        report.insight_json = payload
        report.status = "completed"
        report.error_message = None
        db.commit()
        logger.info("save_plan_archive_insight_result: saved report=%s request=%s", report.id, request.id)
        return True
    except Exception as exc:
        if is_connection_error(exc):
            logger.warning("save_plan_archive_insight_result connection error: %s", exc)
        else:
            logger.error("save_plan_archive_insight_result error: %s", exc, exc_info=True)
        db.rollback()
        return False
