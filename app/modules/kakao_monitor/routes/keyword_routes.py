"""키워드 관리 API."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoWatchConfig, KakaoKeyword

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])


# ========== Schemas ==========

class KeywordOut(BaseModel):
    id: int
    config_id: int
    keyword: str
    action_type: str
    is_active: bool

    class Config:
        from_attributes = True


class KeywordCreate(BaseModel):
    keyword: str
    action_type: str = KakaoKeyword.ACTION_TYPE_COLLECT


# ========== Helpers ==========

def _normalize_keyword(keyword: str) -> str:
    normalized = (keyword or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="keyword must not be blank")
    return normalized


def _normalize_action_type(action_type: str) -> str:
    candidate = (action_type or "").strip().lower()
    if candidate in KakaoKeyword.VALID_ACTION_TYPES:
        return candidate
    raise HTTPException(
        status_code=422,
        detail="action_type must be one of ['collect', 'alert_only']",
    )


# ========== Routes ==========

@router.get("/configs/{config_id}/keywords", response_model=List[KeywordOut])
def get_keywords(config_id: int, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return config.keywords


@router.post("/configs/{config_id}/keywords", response_model=KeywordOut, status_code=201)
def add_keyword(config_id: int, body: KeywordCreate, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    normalized_keyword = _normalize_keyword(body.keyword)
    normalized_action = _normalize_action_type(body.action_type)

    lower_keyword = normalized_keyword.lower()
    has_duplicate = any(
        (kw.keyword or "").strip().lower() == lower_keyword
        for kw in config.keywords
    )
    if has_duplicate:
        raise HTTPException(status_code=409, detail="keyword already exists")

    kw = KakaoKeyword(
        config_id=config_id,
        keyword=normalized_keyword,
        action_type=normalized_action,
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return kw


@router.delete("/keywords/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    kw = db.query(KakaoKeyword).filter(KakaoKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(kw)
    db.commit()
