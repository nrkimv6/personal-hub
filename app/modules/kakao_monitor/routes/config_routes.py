"""
감시 설정 CRUD API.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoWatchConfig, KakaoKeyword

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])


# ========== Schemas ==========

class KeywordOut(BaseModel):
    id: int
    keyword: str
    action_type: str
    is_active: bool

    class Config:
        from_attributes = True


class ConfigOut(BaseModel):
    id: int
    chat_name: str
    polling_interval_sec: int
    is_active: bool
    keyword_count: int

    class Config:
        from_attributes = True


class ConfigCreate(BaseModel):
    chat_name: str
    polling_interval_sec: int = 3
    keywords: List[str] = []


class ConfigUpdate(BaseModel):
    chat_name: Optional[str] = None
    polling_interval_sec: Optional[int] = None


# ========== Routes ==========

@router.get("/configs", response_model=List[ConfigOut])
def get_configs(db: Session = Depends(get_db)):
    configs = db.query(KakaoWatchConfig).all()
    result = []
    for c in configs:
        result.append(ConfigOut(
            id=c.id,
            chat_name=c.chat_name,
            polling_interval_sec=c.polling_interval_sec,
            is_active=c.is_active,
            keyword_count=len(c.keywords),
        ))
    return result


@router.post("/configs", response_model=ConfigOut, status_code=201)
def create_config(body: ConfigCreate, db: Session = Depends(get_db)):
    config = KakaoWatchConfig(
        chat_name=body.chat_name,
        polling_interval_sec=body.polling_interval_sec,
    )
    db.add(config)
    db.flush()

    for kw_text in body.keywords:
        if kw_text.strip():
            kw = KakaoKeyword(
                config_id=config.id,
                keyword=kw_text.strip(),
                action_type="collect",
            )
            db.add(kw)

    db.commit()
    db.refresh(config)
    return ConfigOut(
        id=config.id,
        chat_name=config.chat_name,
        polling_interval_sec=config.polling_interval_sec,
        is_active=config.is_active,
        keyword_count=len(config.keywords),
    )


@router.put("/configs/{config_id}", response_model=ConfigOut)
def update_config(config_id: int, body: ConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    if body.chat_name is not None:
        config.chat_name = body.chat_name
    if body.polling_interval_sec is not None:
        config.polling_interval_sec = body.polling_interval_sec

    db.commit()
    db.refresh(config)
    return ConfigOut(
        id=config.id,
        chat_name=config.chat_name,
        polling_interval_sec=config.polling_interval_sec,
        is_active=config.is_active,
        keyword_count=len(config.keywords),
    )


@router.delete("/configs/{config_id}", status_code=204)
def delete_config(config_id: int, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    db.delete(config)
    db.commit()


@router.patch("/configs/{config_id}/toggle", response_model=ConfigOut)
def toggle_config(config_id: int, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    config.is_active = not config.is_active
    db.commit()
    db.refresh(config)
    return ConfigOut(
        id=config.id,
        chat_name=config.chat_name,
        polling_interval_sec=config.polling_interval_sec,
        is_active=config.is_active,
        keyword_count=len(config.keywords),
    )
