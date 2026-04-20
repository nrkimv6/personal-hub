"""Requeue unrecoverable Instagram mojibake requests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.modules.instagram.services.llm_classifier_service import LLMClassifierService
from scripts.diagnostics.recover_instagram_llm_missing_events import load_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create new Instagram LLM requests for unrecoverable mojibake rows."
    )
    parser.add_argument("--request-id", type=int, help="Requeue one specific llm_requests.id only.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--request-source")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--apply", action="store_true", help="Actually enqueue new requests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = SessionLocal()
    try:
        candidates = [candidate for candidate in load_candidates(session, args) if candidate.action == "requeue"]
        print(f"requeue_candidates={len(candidates)}")

        if not args.apply:
            for candidate in candidates:
                print(
                    f"request_id={candidate.request_id} post_id={candidate.post_id} "
                    f"action=requeue reason={candidate.reason}"
                )
            print("mode=dry-run")
            return 0

        service = LLMClassifierService(session)
        created = 0
        skipped = 0
        for candidate in candidates:
            request = service.create_request(
                post_id=candidate.post_id,
                trigger_tag="event",
                requested_by="requeue_mojibake",
            )
            if request is None:
                skipped += 1
                print(
                    f"request_id={candidate.request_id} post_id={candidate.post_id} "
                    "action=skip reason=create_request_failed"
                )
                continue
            created += 1
            print(
                f"request_id={candidate.request_id} post_id={candidate.post_id} "
                f"action=requeued new_request_id={request.id}"
            )

        print(f"mode=apply created={created} skipped={skipped}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
