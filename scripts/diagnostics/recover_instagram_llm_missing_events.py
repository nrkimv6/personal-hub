"""Recover missing Event rows from completed Instagram LLM requests.

Use cases:
1. Dry-run: list completed Instagram LLM requests whose normalized payload says
   ``tag=이벤트`` but no linked ``events`` row exists for the source post.
2. Apply: create the missing Event row and relink ``instagram_posts.classified_*``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.models.event import Event
from app.models.instagram_post import InstagramPost
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.claude_worker.worker.worker import (
    extract_instagram_payload,
    instagram_payload_has_mojibake,
    repair_instagram_payload_mojibake,
    save_instagram_result,
    try_reverse_decode_text as _worker_try_reverse_decode_text,
)


TAG_EVENT = "이벤트"


@dataclass
class Candidate:
    request_id: int
    post_id: int
    request_source: Optional[str]
    processed_at: Optional[datetime]
    account: str
    summary: Optional[str]
    organizer: Optional[str]
    event_start: Optional[date]
    event_end: Optional[date]
    event_url: Optional[str]
    existing_event_id: Optional[int]
    classified_type: Optional[str]
    classified_id: Optional[int]
    action: str
    reason: str
    payload: dict[str, Any]


@dataclass
class RecoveryOutcome:
    changed: bool
    action: str
    reason: str
    event_id: Optional[int] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find or recover missing Event rows from completed Instagram LLM requests."
    )
    parser.add_argument("--request-id", type=int, help="Recover one specific llm_requests.id only.")
    parser.add_argument("--limit", type=int, default=50, help="Max candidate rows to inspect. Default: 50")
    parser.add_argument("--request-source", help="Filter by exact request_source, e.g. instagram_event")
    parser.add_argument(
        "--since",
        help="Filter by processed_at >= YYYY-MM-DD (inclusive). Example: --since 2026-04-14",
    )
    parser.add_argument(
        "--until",
        help="Filter by processed_at <= YYYY-MM-DD (inclusive, end-of-day). Example: --until 2026-04-16",
    )
    parser.add_argument("--apply", action="store_true", help="Actually create/relink rows. Default is dry-run.")
    parser.add_argument(
        "--allow-duplicate-url",
        action="store_true",
        help="Allow creating a missing event even if another event already uses the same event_url.",
    )
    return parser.parse_args()


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def normalize_payload(result_text: Optional[str], raw_response: Optional[str]) -> Optional[dict[str, Any]]:
    """Normalize stored request.result/raw_response into the inner Instagram payload."""
    payload = extract_instagram_payload(result_text, raw_response)
    repaired_payload, _ = repair_instagram_payload_mojibake(payload)
    return repaired_payload


def try_reverse_decode_text(text: Optional[str]) -> Optional[str]:
    return _worker_try_reverse_decode_text(text)


def build_candidate(session, request: LLMRequest) -> Optional[Candidate]:
    try:
        post_id = int(request.caller_id)
    except (TypeError, ValueError):
        return None

    post = session.query(InstagramPost).filter(InstagramPost.id == post_id).first()
    if not post:
        return None

    original_payload = extract_instagram_payload(request.result, request.raw_response)
    payload = normalize_payload(request.result, request.raw_response)
    payload_repaired = payload is not None and payload != original_payload
    payload_mojibake = instagram_payload_has_mojibake(original_payload, request.raw_response)

    if not payload:
        return None
    if payload.get("tag") != TAG_EVENT:
        if payload_mojibake:
            return Candidate(
                request_id=request.id,
                post_id=post_id,
                request_source=request.request_source,
                processed_at=request.processed_at,
                account=post.account,
                summary=payload.get("summary"),
                organizer=payload.get("organizer"),
                event_start=None,
                event_end=None,
                event_url=None,
                existing_event_id=None,
                classified_type=post.classified_type,
                classified_id=post.classified_id,
                action="requeue",
                reason="requeue_required",
                payload=payload,
            )
        return None

    existing_event = (
        session.query(Event)
        .filter(Event.source_instagram_post_id == post_id)
        .order_by(Event.id.desc())
        .first()
    )

    urls = payload.get("urls") or []
    if not isinstance(urls, list):
        urls = []
    event_period = payload.get("event_period") or {}
    if not isinstance(event_period, dict):
        event_period = {}

    classified_ok = (
        existing_event is not None
        and post.classified_type == "event"
        and post.classified_id == existing_event.id
    )

    if classified_ok:
        action = "skip"
        reason = "already_linked"
    elif existing_event is not None:
        action = "relink"
        reason = "event_exists_but_post_link_missing"
    elif payload_repaired:
        action = "repair"
        reason = "repairable_mojibake"
    else:
        action = "create"
        reason = "missing_event_row"

    return Candidate(
        request_id=request.id,
        post_id=post_id,
        request_source=request.request_source,
        processed_at=request.processed_at,
        account=post.account,
        summary=payload.get("summary"),
        organizer=payload.get("organizer"),
        event_start=parse_date(event_period.get("start")),
        event_end=parse_date(event_period.get("end")),
        event_url=urls[0] if urls else None,
        existing_event_id=existing_event.id if existing_event else None,
        classified_type=post.classified_type,
        classified_id=post.classified_id,
        action=action,
        reason=reason,
        payload=payload,
    )


def recover_candidate(session, candidate: Candidate, allow_duplicate_url: bool = False) -> RecoveryOutcome:
    post = session.query(InstagramPost).filter(InstagramPost.id == candidate.post_id).first()
    if not post:
        return RecoveryOutcome(False, "skip", "post_not_found")

    if candidate.action == "skip":
        return RecoveryOutcome(False, "skip", candidate.reason, candidate.existing_event_id)

    if candidate.action == "requeue":
        return RecoveryOutcome(False, "requeue", candidate.reason, candidate.existing_event_id)

    if candidate.action == "relink":
        existing_event = session.query(Event).filter(Event.id == candidate.existing_event_id).first()
        if not existing_event:
            return RecoveryOutcome(False, "skip", "existing_event_missing")
        post.classified_type = "event"
        post.classified_id = existing_event.id
        post.classified_at = candidate.processed_at or datetime.now()
        session.commit()
        return RecoveryOutcome(True, "relink", "post_relinked_to_existing_event", existing_event.id)

    urls = candidate.payload.get("urls") or []
    if not isinstance(urls, list):
        urls = []

    if candidate.event_url and not allow_duplicate_url:
        duplicate = (
            session.query(Event)
            .filter(
                Event.event_url == candidate.event_url,
                Event.source_instagram_post_id != candidate.post_id,
            )
            .order_by(Event.id.desc())
            .first()
        )
        if duplicate:
            return RecoveryOutcome(False, "skip", f"duplicate_url_event:{duplicate.id}", duplicate.id)

    if not save_instagram_result(session, candidate.post_id, candidate.payload):
        session.rollback()
        return RecoveryOutcome(False, "skip", "save_instagram_result_failed")

    if candidate.processed_at:
        post.classified_at = candidate.processed_at
    session.commit()
    session.refresh(post)
    return RecoveryOutcome(
        True,
        "repair" if candidate.action == "repair" else "create",
        candidate.reason if candidate.action == "repair" else "event_created",
        post.classified_id,
    )


def load_candidates(session, args: argparse.Namespace) -> list[Candidate]:
    query = (
        session.query(LLMRequest)
        .filter(
            LLMRequest.caller_type == "instagram",
            LLMRequest.status == "completed",
            LLMRequest.deleted_at.is_(None),
        )
        .order_by(LLMRequest.id.desc())
    )

    if args.request_id is not None:
        query = query.filter(LLMRequest.id == args.request_id)
    if args.request_source:
        query = query.filter(LLMRequest.request_source == args.request_source)

    since_date = parse_date(getattr(args, "since", None))
    until_date = parse_date(getattr(args, "until", None))
    if since_date is not None:
        since_dt = datetime.combine(since_date, datetime.min.time())
        query = query.filter(LLMRequest.processed_at >= since_dt)
    if until_date is not None:
        from datetime import time as dt_time
        until_dt = datetime.combine(until_date, dt_time(23, 59, 59, 999999))
        query = query.filter(LLMRequest.processed_at <= until_dt)

    requests = query.limit(args.limit).all()
    candidates: list[Candidate] = []
    for request in requests:
        candidate = build_candidate(session, request)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def print_candidates(candidates: list[Candidate]) -> None:
    print(f"candidates={len(candidates)}")
    for candidate in candidates:
        print(
            " | ".join(
                [
                    f"request_id={candidate.request_id}",
                    f"post_id={candidate.post_id}",
                    f"action={candidate.action}",
                    f"reason={candidate.reason}",
                    f"classified={candidate.classified_type or '-'}:{candidate.classified_id or '-'}",
                    f"existing_event={candidate.existing_event_id or '-'}",
                    f"summary={candidate.summary or '-'}",
                ]
            )
        )
    # dry-run summary by action
    from collections import Counter
    counts = Counter(c.action for c in candidates)
    print(
        f"summary create={counts.get('create', 0)} "
        f"relink={counts.get('relink', 0)} "
        f"repair={counts.get('repair', 0)} "
        f"requeue={counts.get('requeue', 0)} "
        f"skip={counts.get('skip', 0)}"
    )


def main() -> int:
    args = parse_args()
    session = SessionLocal()
    try:
        candidates = load_candidates(session, args)
        print_candidates(candidates)

        if not args.apply:
            print("mode=dry-run")
            return 0

        changed = 0
        skipped = 0
        for candidate in candidates:
            try:
                outcome = recover_candidate(
                    session,
                    candidate,
                    allow_duplicate_url=args.allow_duplicate_url,
                )
            except Exception as exc:  # pragma: no cover - defensive CLI handling
                session.rollback()
                skipped += 1
                print(
                    f"request_id={candidate.request_id} post_id={candidate.post_id} "
                    f"action=error reason={type(exc).__name__}:{exc}"
                )
                continue

            if outcome.changed:
                changed += 1
            else:
                skipped += 1
            print(
                f"request_id={candidate.request_id} post_id={candidate.post_id} "
                f"action={outcome.action} reason={outcome.reason} event_id={outcome.event_id or '-'}"
            )

        print(f"mode=apply changed={changed} skipped={skipped}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
