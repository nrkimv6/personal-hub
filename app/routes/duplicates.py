"""Event duplicate review API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import UserInfo, require_admin
from app.database import get_db
from app.models.dismissed_duplicate import DismissedDuplicate
from app.schemas.duplicate_merge import (
    DismissDuplicateRequest,
    DismissDuplicateResponse,
    DuplicateCandidateResponse,
    MergeExecuteRequest,
    MergeExecuteResponse,
    MergePreviewResponse,
)
from app.services.duplicate_detection_service import duplicate_detection_service
from app.services.event_merge_service import event_merge_service

router = APIRouter(prefix="/api/v1/duplicates", tags=["event-duplicates"])


@router.get("/candidates", response_model=list[DuplicateCandidateResponse])
def get_duplicate_candidates(
    entity_type: str = Query("event"),
    min_similarity: float = Query(0.5, ge=0.0, le=1.0),
    max_similarity: float = Query(0.99, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    try:
        return duplicate_detection_service.find_duplicate_candidates(
            db=db,
            entity_type=entity_type,
            min_similarity=min_similarity,
            max_similarity=max_similarity,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/preview", response_model=MergePreviewResponse)
def get_merge_preview(
    primary_id: int = Query(..., gt=0),
    secondary_id: int = Query(..., gt=0),
    entity_type: str = Query("event"),
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    if entity_type != "event":
        raise HTTPException(status_code=400, detail="Only event merge is supported")
    try:
        return event_merge_service.preview_merge(db, primary_id, secondary_id)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/merge", response_model=MergeExecuteResponse)
def merge_duplicate(
    request: MergeExecuteRequest,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    try:
        return event_merge_service.execute_merge(db, request)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/dismiss", response_model=DismissDuplicateResponse)
def dismiss_duplicate(
    request: DismissDuplicateRequest,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    if request.entity_type != "event":
        raise HTTPException(status_code=400, detail="Only event duplicates are supported")
    entity1_id, entity2_id = DismissedDuplicate.ordered_pair(request.entity1_id, request.entity2_id)
    dismissed_by = request.dismissed_by or admin.email
    row = DismissedDuplicate(
        entity_type=request.entity_type,
        entity1_id=entity1_id,
        entity2_id=entity2_id,
        dismissed_by=dismissed_by,
    )
    try:
        db.add(row)
        db.commit()
    except IntegrityError:
        db.rollback()
    return DismissDuplicateResponse(
        entity_type=request.entity_type,
        entity1_id=entity1_id,
        entity2_id=entity2_id,
        dismissed=True,
    )
