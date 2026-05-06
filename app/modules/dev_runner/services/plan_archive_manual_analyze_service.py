"""Manual Plan Archive analyze service."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.models.plan_record import PlanRecord
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services.plan_archive_prompt_policy import (
    PromptPolicyContext,
    build_plan_archive_prompt,
)
from app.modules.claude_worker.services.plan_analyze_handler import (
    save_plan_archive_result,
)

REQUIRED_ANALYZE_FIELDS = (
    "category",
    "tags",
    "summary",
    "superseded_by",
    "intent",
    "trigger",
    "scope",
)


def _record_snapshot(record: PlanRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename_hash": record.filename_hash,
        "file_path": record.file_path,
        "category": record.category,
        "tags": record.tags,
        "summary": record.summary,
        "superseded_by": record.superseded_by,
        "intent": record.intent,
        "trigger": record.trigger,
        "scope": json.loads(record.scope) if isinstance(record.scope, str) and record.scope.startswith("[") else record.scope,
        "llm_processed_at": record.llm_processed_at.isoformat() if record.llm_processed_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


class PlanArchiveManualAnalyzeService:
    """Run one archive record through the plan_archive_analyze prompt."""

    def __init__(self, db: Session):
        self.db = db

    def build_input(self, record_id: int, source: str | None = None) -> tuple[PlanRecord | None, str, str | None]:
        record = self.db.query(PlanRecord).filter(PlanRecord.id == record_id).first()
        if not record:
            return None, "", "RECORD_NOT_FOUND"

        source_mode = (source or "auto").strip() or "auto"
        if source_mode not in {"auto", "raw_content", "file_path"}:
            return record, "", f"INVALID_SOURCE: {source_mode}"

        if source_mode in {"auto", "raw_content"} and record.raw_content:
            return record, record.raw_content, None

        if source_mode in {"auto", "file_path"} and record.file_path:
            candidates = [Path(record.file_path)]
            if not candidates[0].is_absolute():
                candidates.append(PROJECT_ROOT / record.file_path)
            for path in candidates:
                if path.exists() and path.is_file():
                    return record, path.read_text(encoding="utf-8", errors="replace"), None

        return record, "", "EMPTY_PLAN_CONTENT"

    def parse_executor_result(self, executor_result: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[str]]:
        warnings = list(executor_result.get("warnings") or [])
        raw_response = str(executor_result.get("raw_response") or "")
        payload: Any = executor_result.get("parsed")
        if payload is None:
            payload = executor_result.get("result")
        if payload is None:
            payload = raw_response

        if isinstance(payload, dict):
            parsed = payload
        elif isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                warnings.append(f"PARSE_ERROR: {exc}")
                return None, raw_response or payload, warnings
        else:
            warnings.append(f"PARSE_ERROR: unsupported payload type {type(payload).__name__}")
            return None, raw_response, warnings

        missing = [field for field in REQUIRED_ANALYZE_FIELDS if field not in parsed]
        if missing:
            warnings.append(f"MISSING_FIELDS: {', '.join(missing)}")
        return parsed, raw_response or json.dumps(parsed, ensure_ascii=False), warnings

    def analyze(
        self,
        record_id: int,
        *,
        mode: str = "preview",
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 120,
        include_prompt: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        record, content, input_error = self.build_input(record_id, source)
        if not record:
            return {"success": False, "error": input_error or "RECORD_NOT_FOUND", "record_id": record_id}
        if input_error:
            return {
                "success": False,
                "error": input_error,
                "mode": mode,
                "record_id": record.id,
                "filename_hash": record.filename_hash,
                "file_path": record.file_path,
                "warnings": [input_error],
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "prompt_policy_id": None,
                "prompt_policy_version": None,
            }

        llm_service = LLMService(self.db)
        resolved_provider, resolved_model = llm_service.resolve_provider_model(
            "plan_archive_analyze",
            provider=provider,
            model=model,
        )
        prompt, prompt_policy_id, prompt_policy_version = build_plan_archive_prompt(
            PromptPolicyContext(
                caller_type="plan_archive_analyze",
                provider=resolved_provider,
                model=resolved_model,
                filename=Path(record.file_path).name,
                existing_categories=self._existing_categories(),
            ),
            content,
        )
        executor_result = llm_service.execute_llm(
            prompt,
            provider=resolved_provider,
            model=resolved_model,
            timeout=timeout_seconds,
            parse_json=True,
            cli_options={"parse_json": True},
        )
        parsed, raw_response, warnings = self.parse_executor_result(executor_result)
        success = bool(executor_result.get("success")) and parsed is not None

        response: dict[str, Any] = {
            "success": success,
            "mode": mode,
            "result": parsed or {},
            "raw_response": raw_response,
            "provider": resolved_provider,
            "model": resolved_model,
            "record_id": record.id,
            "filename_hash": record.filename_hash,
            "file_path": record.file_path,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "prompt_preview": prompt if include_prompt else None,
            "prompt_policy_id": prompt_policy_id,
            "prompt_policy_version": prompt_policy_version,
            "warnings": warnings,
            "saved": False,
            "record_after": None,
            "save_error": None,
            "save_outcome_status": None,
            "save_outcome_reason": None,
        }
        if not executor_result.get("success"):
            response["error"] = executor_result.get("error") or "EXECUTOR_FAILED"
        elif parsed is None:
            response["error"] = "PARSE_ERROR"

        if mode == "apply" and success and parsed is not None:
            request_like = SimpleNamespace(
                caller_id=record.filename_hash,
                caller_type="plan_archive_analyze",
            )
            try:
                save_ok = save_plan_archive_result(
                    self.db,
                    request_like,
                    {"success": True, "result": parsed, "raw_response": raw_response},
                )
            except Exception as exc:
                response["saved"] = False
                response["save_error"] = str(exc)
                response["save_outcome_status"] = "error"
                response["save_outcome_reason"] = str(exc)
                return response
            response["saved"] = bool(save_ok)
            if save_ok:
                response["save_outcome_status"] = "saved"
                self.db.refresh(record)
                response["record_after"] = _record_snapshot(record)
            else:
                response["save_error"] = "SAVE_PLAN_ARCHIVE_RESULT_FAILED"
                response["save_outcome_status"] = "failed"
                response["save_outcome_reason"] = "SAVE_PLAN_ARCHIVE_RESULT_FAILED"

        return response

    def _existing_categories(self) -> list[str]:
        rows = (
            self.db.query(PlanRecord.category)
            .filter(PlanRecord.category.isnot(None))
            .distinct()
            .all()
        )
        categories = sorted({row[0] for row in rows if row[0]})
        return categories or [
            "naver-booking",
            "instagram",
            "google-search",
            "activity",
            "claude-worker",
            "video",
            "infra",
            "writing",
            "common",
        ]
