"""Shared helpers for Plan Archive route modules."""
from typing import Any, Optional

from sqlalchemy.orm import Session

_FAILURE_CATEGORY_ERROR_CODES = {
    "gemini_cli_not_found": "GEMINI_CLI_NOT_FOUND",
    "gemini_auth_required": "GEMINI_AUTH_REQUIRED",
    "gemini_cli_error": "GEMINI_CLI_ERROR",
}

def _archive_request_error_code(
    failure_category: Optional[str],
    error_message: Optional[str],
) -> Optional[str]:
    category = (failure_category or "").strip()
    if category in _FAILURE_CATEGORY_ERROR_CODES:
        return _FAILURE_CATEGORY_ERROR_CODES[category]

    message = error_message or ""
    for code in _FAILURE_CATEGORY_ERROR_CODES.values():
        if code in message:
            return code
    return None


def _extract_profile_fields(cli: dict) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    profile_key = cli.get("profile_key") if isinstance(cli.get("profile_key"), str) else None
    target_label = cli.get("target_label") if isinstance(cli.get("target_label"), str) else None
    engine = None
    profile_name = None
    cps = cli.get("candidate_profiles")
    if isinstance(cps, list) and cps:
        first = cps[0] if isinstance(cps[0], dict) else None
        if first:
            engine = str(first.get("engine") or "").strip() or None
            profile_name = str(first.get("profile_name") or "").strip() or None
    return profile_key, engine, profile_name, target_label


def _parse_cli_options_text(text: str | None) -> dict[str, Any]:
    import json as _json_cli

    try:
        parsed = _json_cli.loads(text) if text else {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _archive_target_fields(
    cli: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    actual_engine: str | None = None,
    actual_profile_name: str | None = None,
) -> dict[str, Any]:
    """Return requested/effective/actual target read-back fields.

    Older requests only have candidate_profiles/profile_key/target_label. Newer
    requests carry requested_target/effective_target snapshots.
    """
    legacy_profile_key, legacy_engine, legacy_profile_name, legacy_target_label = _extract_profile_fields(cli)
    requested = _dict_or_empty(cli.get("requested_target"))
    effective = _dict_or_empty(cli.get("effective_target"))

    requested_provider = requested.get("provider") or provider
    requested_model = requested.get("model") if requested.get("model") is not None else model
    requested_engine = requested.get("engine") or legacy_engine
    requested_profile_name = requested.get("profile_name") or legacy_profile_name
    requested_profile_key = requested.get("profile_key") or legacy_profile_key
    target_label = requested.get("label") or legacy_target_label
    requested_dedupe_key = requested.get("dedupe_key") if isinstance(requested.get("dedupe_key"), str) else None
    effective_provider = effective.get("provider") or provider
    effective_model = effective.get("model") if effective.get("model") is not None else model
    effective_dedupe_key = effective.get("dedupe_key") if isinstance(effective.get("dedupe_key"), str) else requested_dedupe_key
    requested_target = {
        "provider": requested_provider,
        "model": requested_model,
        "profile_key": requested_profile_key,
        "engine": requested_engine,
        "profile_name": requested_profile_name,
        "label": target_label,
        "target_label": target_label,
        "dedupe_key": requested_dedupe_key,
    }
    effective_target = {
        "provider": effective_provider,
        "model": effective_model,
        "profile_key": effective.get("profile_key") or requested_profile_key,
        "engine": effective.get("engine") or requested_engine,
        "profile_name": effective.get("profile_name") or requested_profile_name,
        "label": effective.get("label") or target_label,
        "target_label": effective.get("label") or target_label,
        "dedupe_key": effective_dedupe_key,
    }
    has_actual_assignment = bool(actual_engine or actual_profile_name)
    actual_target = {
        "provider": provider,
        "model": model,
        "profile_key": requested_profile_key if has_actual_assignment else None,
        "engine": actual_engine,
        "profile_name": actual_profile_name,
        "label": target_label if has_actual_assignment else None,
        "target_label": target_label if has_actual_assignment else None,
        "dedupe_key": effective_dedupe_key if has_actual_assignment else None,
    }
    assigned_profile = None
    if actual_engine or actual_profile_name:
        assigned_profile = {
            "provider": actual_engine,
            "model": model,
            "profile_key": requested_profile_key,
            "engine": actual_engine,
            "profile_name": actual_profile_name,
        }
    save_outcome = _dict_or_empty(cli.get("plan_archive_save_outcome"))

    return {
        "profile_key": requested_profile_key,
        "engine": requested_engine,
        "profile_name": requested_profile_name,
        "target_label": target_label,
        "requested_provider": requested_provider,
        "requested_model": requested_model,
        "requested_engine": requested_engine,
        "requested_profile_name": requested_profile_name,
        "requested_profile_key": requested_profile_key,
        "effective_provider": effective_provider,
        "effective_model": effective_model,
        "actual_provider": provider,
        "actual_model": model,
        "actual_engine": actual_engine,
        "actual_profile_name": actual_profile_name,
        "requested_target": requested_target,
        "effective_target": effective_target,
        "actual_target": actual_target,
        "effective_provider_model": effective_target,
        "actual_provider_model": actual_target,
        "assigned_profile": assigned_profile,
        "save_outcome_status": save_outcome.get("status"),
        "save_outcome_reason": save_outcome.get("reason"),
    }


def _latest_profile_assignment(db: Session, request_id: int) -> tuple[str | None, str | None]:
    try:
        from app.modules.claude_worker.models.llm_request import LLMProfileAssignment

        assignment = (
            db.query(LLMProfileAssignment)
            .filter(LLMProfileAssignment.request_id == request_id)
            .order_by(LLMProfileAssignment.selected_at.desc())
            .first()
        )
        if assignment:
            return assignment.engine, assignment.profile_name
    except Exception:
        db.rollback()
        return None, None
    return None, None

__all__ = [
    "_archive_request_error_code",
    "_extract_profile_fields",
    "_parse_cli_options_text",
    "_dict_or_empty",
    "_archive_target_fields",
    "_latest_profile_assignment",
]
