"""
키워드 관리 API.
"""
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
    action_type: str = "collect"


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

    kw = KakaoKeyword(
        config_id=config_id,
        keyword=body.keyword.strip(),
        action_type=body.action_type,
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
