"""Expo 운영 콘솔 API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import UserInfo, require_admin
from app.database import get_db
from app.schemas.expo import (
    ExpoCollectionStatusResponse,
    ExpoExportPayload,
    ExpoExportRecordResponse,
    ExpoPipelineStatusResponse,
    ExpoPublishedStatusResponse,
)
from app.services.expo_service import ExpoNotFoundError, ExpoService

router = APIRouter(prefix="/api/v1/expo", tags=["expo"])


@router.get("/{slug}/pipeline-status", response_model=ExpoPipelineStatusResponse)
async def get_expo_pipeline_status(
    slug: str,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    service = ExpoService(db)
    try:
        return service.get_pipeline_status(slug)
    except ExpoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{slug}/collection-status", response_model=ExpoCollectionStatusResponse)
async def get_expo_collection_status(
    slug: str,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    service = ExpoService(db)
    try:
        return service.get_collection_status(slug)
    except ExpoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{slug}/published-status", response_model=ExpoPublishedStatusResponse)
async def get_expo_published_status(
    slug: str,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    service = ExpoService(db)
    try:
        return service.get_published_status(slug)
    except ExpoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{slug}/exports/record",
    response_model=ExpoExportRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_expo_export(
    slug: str,
    payload: ExpoExportPayload,
    db: Session = Depends(get_db),
    _: UserInfo = Depends(require_admin),
):
    service = ExpoService(db)
    try:
        return service.record_export(slug, payload)
    except ExpoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
