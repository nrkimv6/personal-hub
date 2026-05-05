"""Profile claim/audit helpers for LLM request execution."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.claude_worker.models.llm_request import (
    LLMProfileAssignment,
    LLMRequestProfileClaim,
)


class ProfileClaimService:
    def __init__(self, db: Session):
        self.db = db

    def claim(self, request_id: int, engine: str, profile_name: str) -> Optional[LLMRequestProfileClaim]:
        claim = LLMRequestProfileClaim(
            request_id=request_id,
            engine=engine,
            profile_name=profile_name,
            claimed_at=datetime.now(),
        )
        assignment = LLMProfileAssignment(
            request_id=request_id,
            engine=engine,
            profile_name=profile_name,
            selected_at=claim.claimed_at,
        )
        self.db.add(claim)
        self.db.add(assignment)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return None
        return claim

    def release(
        self,
        request_id: int,
        *,
        stop_reason: str,
        error_summary: str | None = None,
    ) -> None:
        now = datetime.now()
        claim = (
            self.db.query(LLMRequestProfileClaim)
            .filter(LLMRequestProfileClaim.request_id == request_id)
            .first()
        )
        if claim:
            self.db.delete(claim)

        assignments = (
            self.db.query(LLMProfileAssignment)
            .filter(LLMProfileAssignment.request_id == request_id)
            .all()
        )
        for assignment in assignments:
            if assignment.released_at is None:
                assignment.released_at = now
                assignment.stop_reason = stop_reason
                assignment.error_summary = error_summary
        self.db.commit()
