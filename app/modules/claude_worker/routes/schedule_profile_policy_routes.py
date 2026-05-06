"""Schedule × LLM profile policy endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.models.llm_request import LLMScheduleProfilePolicy
from app.modules.claude_worker.services.schedule_profile_policy_service import ScheduleProfilePolicyService

router = APIRouter(tags=["llm"])


class ScheduleProfileWindow(BaseModel):
    start: str
    end: str
    days: Optional[list[int]] = None


class ScheduleProfilePolicyItem(BaseModel):
    id: Optional[int] = None
    schedule_id: Optional[int] = None
    target_type: Optional[str] = None
    engine: str
    profile_name: str
    enabled: bool = True
    priority: int = 0
    allowed_windows: list[ScheduleProfileWindow] = Field(default_factory=list)
    quiet_windows: list[ScheduleProfileWindow] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScheduleProfilePoliciesResponse(BaseModel):
    policies: list[ScheduleProfilePolicyItem]


class ScheduleProfilePoliciesUpdateRequest(BaseModel):
    policies: list[ScheduleProfilePolicyItem] = Field(default_factory=list)


def _policy_to_item(row: LLMScheduleProfilePolicy) -> ScheduleProfilePolicyItem:
    return ScheduleProfilePolicyItem(
        id=row.id,
        schedule_id=row.schedule_id,
        target_type=row.target_type,
        engine=row.engine,
        profile_name=row.profile_name,
        enabled=row.enabled,
        priority=row.priority,
        allowed_windows=json.loads(row.allowed_windows or "[]"),
        quiet_windows=json.loads(row.quiet_windows or "[]"),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/schedule-profile-policies", response_model=ScheduleProfilePoliciesResponse)
def list_schedule_profile_policies(db: Session = Depends(get_db)):
    service = ScheduleProfilePolicyService(db)
    return ScheduleProfilePoliciesResponse(policies=[_policy_to_item(row) for row in service.list()])


@router.put("/schedule-profile-policies", response_model=ScheduleProfilePoliciesResponse)
def replace_schedule_profile_policies(
    body: ScheduleProfilePoliciesUpdateRequest,
    db: Session = Depends(get_db),
):
    service = ScheduleProfilePolicyService(db)
    try:
        rows = service.replace_all([item.model_dump(exclude={"id", "created_at", "updated_at"}) for item in body.policies])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScheduleProfilePoliciesResponse(policies=[_policy_to_item(row) for row in rows])
