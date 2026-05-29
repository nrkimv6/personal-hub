"""Plan outcome/evaluation parsing utilities."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.modules.dev_runner.schemas import OutcomeSummaryResponse, OutcomeVerifierResponse

_OUTCOME_HEAD_RE = re.compile(r"^#{2,3}\s+(?:plan\s+)?outcome(?:\s*/\s*evaluation)?\s*$", re.IGNORECASE)
_NEXT_HEAD_RE = re.compile(r"^#{2,3}\s+")
_FIELD_RE = re.compile(r"^\s*(?:[-*]\s*)?(Outcome|Verifier|Rollback signal|Evidence source)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def _strip_inline_status(value: str) -> tuple[str, str]:
    text = value.strip()
    status = "pending"
    status_match = re.search(r"\[(pending|satisfied|passed|failed|blocked)\]\s*$", text, re.IGNORECASE)
    if status_match:
        status = status_match.group(1).lower()
        if status == "passed":
            status = "satisfied"
        text = text[: status_match.start()].strip()
    return text, status


def _collect_outcome_lines(content: str) -> list[str]:
    lines = content.splitlines()
    in_section = False
    collected: list[str] = []
    for line in lines:
        if _OUTCOME_HEAD_RE.match(line.strip()):
            in_section = True
            continue
        if in_section and _NEXT_HEAD_RE.match(line.strip()):
            break
        if in_section:
            collected.append(line)
    return collected


def parse_outcome_summary(content: str, *, updated_at: str | None = None) -> OutcomeSummaryResponse:
    """Parse an optional Outcome section without mutating the plan text."""

    lines = _collect_outcome_lines(content)
    if not lines:
        return OutcomeSummaryResponse(status="absent")

    outcome: str | None = None
    verifiers: list[OutcomeVerifierResponse] = []
    evidence: list[str] = []
    rollback_signal: str | None = None

    for line in lines:
        match = _FIELD_RE.match(line)
        if not match:
            continue
        field = match.group(1).lower()
        value = match.group(2).strip()
        if field == "outcome":
            outcome = value
        elif field == "verifier":
            name, status = _strip_inline_status(value)
            if name:
                verifiers.append(OutcomeVerifierResponse(name=name, status=status))
        elif field == "rollback signal":
            rollback_signal = value
        elif field == "evidence source":
            evidence.append(value)

    status = "pending"
    verifier_statuses = {v.status for v in verifiers}
    if rollback_signal and re.search(r"\b(detected|failed|blocked|true)\b", rollback_signal, re.IGNORECASE):
        status = "blocked"
    elif "failed" in verifier_statuses:
        status = "failed"
    elif "blocked" in verifier_statuses:
        status = "blocked"
    elif outcome and verifiers and verifier_statuses <= {"satisfied"}:
        status = "satisfied"

    return OutcomeSummaryResponse(
        status=status,
        outcome=outcome,
        verifiers=verifiers,
        evidence=evidence,
        rollback_signal=rollback_signal,
        updated_at=updated_at,
    )


def parse_plan_outcome_summary(path: Path, content: str) -> OutcomeSummaryResponse:
    """Build the plan outcome summary with a stable file mtime timestamp."""

    updated_at: str | None = None
    try:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        updated_at = None
    return parse_outcome_summary(content, updated_at=updated_at)


def evaluate_outcome_from_events(
    summary: OutcomeSummaryResponse,
    structured_events: Iterable[dict],
) -> OutcomeSummaryResponse:
    """Apply structured event failure/rollback signals to an already parsed summary."""

    if summary.status == "absent":
        return summary

    for event in structured_events:
        failure = event.get("failure") if isinstance(event, dict) else None
        classification = failure.get("classification") if isinstance(failure, dict) else None
        raw = str(event.get("raw") or event.get("message") or "") if isinstance(event, dict) else ""
        if classification in {"product", "environment", "retryable"}:
            return summary.model_copy(update={"status": "failed", "rollback_signal": raw or summary.rollback_signal})
        if re.search(r"rollback|regression|revert", raw, re.IGNORECASE):
            return summary.model_copy(update={"status": "blocked", "rollback_signal": raw})
    return summary
