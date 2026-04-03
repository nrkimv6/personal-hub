"""감시 설정 CRUD API."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.kakao_monitor import KakaoWatchConfig, KakaoKeyword

router = APIRouter(prefix="/api/v1/kakao-monitor", tags=["kakao-monitor"])

_MIN_POLLING_INTERVAL_SEC = 1
_MAX_POLLING_INTERVAL_SEC = 3600


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
    keywords: List[str] = Field(default_factory=list)


class ConfigUpdate(BaseModel):
    chat_name: Optional[str] = None
    polling_interval_sec: Optional[int] = None


# ========== Helpers ==========

def _to_out(config: KakaoWatchConfig) -> ConfigOut:
    return ConfigOut(
        id=config.id,
        chat_name=config.chat_name,
        polling_interval_sec=config.polling_interval_sec,
        is_active=config.is_active,
        keyword_count=len(config.keywords),
    )


def _validate_chat_name(chat_name: str) -> str:
    normalized = (chat_name or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="chat_name must not be blank")
    return normalized


def _validate_polling_interval(interval: int) -> int:
    if interval < _MIN_POLLING_INTERVAL_SEC or interval > _MAX_POLLING_INTERVAL_SEC:
        raise HTTPException(
            status_code=422,
            detail=f"polling_interval_sec must be {_MIN_POLLING_INTERVAL_SEC}~{_MAX_POLLING_INTERVAL_SEC}",
        )
    return interval


def _get_other_active_config(db: Session, *, exclude_id: int | None = None) -> KakaoWatchConfig | None:
    q = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.is_active.is_(True))
    if exclude_id is not None:
        q = q.filter(KakaoWatchConfig.id != exclude_id)
    return q.order_by(KakaoWatchConfig.id.asc()).first()


# ========== Routes ==========

@router.get("/configs", response_model=List[ConfigOut])
def get_configs(db: Session = Depends(get_db)):
    configs = db.query(KakaoWatchConfig).order_by(KakaoWatchConfig.id.asc()).all()
    return [_to_out(c) for c in configs]


@router.post("/configs", response_model=ConfigOut, status_code=201)
def create_config(body: ConfigCreate, db: Session = Depends(get_db)):
    chat_name = _validate_chat_name(body.chat_name)
    polling_interval = _validate_polling_interval(body.polling_interval_sec)

    active_existing = _get_other_active_config(db)
    if active_existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Only one active kakao monitor config is allowed",
        )

    config = KakaoWatchConfig(
        chat_name=chat_name,
        polling_interval_sec=polling_interval,
        is_active=True,
    )
    db.add(config)
    db.flush()

    seen_keywords: set[str] = set()
    for kw_text in body.keywords:
        normalized = (kw_text or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen_keywords:
            continue
        seen_keywords.add(lowered)
        db.add(
            KakaoKeyword(
                config_id=config.id,
                keyword=normalized,
                action_type=KakaoKeyword.ACTION_TYPE_COLLECT,
            )
        )

    db.commit()
    db.refresh(config)
    return _to_out(config)


@router.put("/configs/{config_id}", response_model=ConfigOut)
def update_config(config_id: int, body: ConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(KakaoWatchConfig).filter(KakaoWatchConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    if body.chat_name is not None:
        config.chat_name = _validate_chat_name(body.chat_name)
    if body.polling_interval_sec is not None:
        config.polling_interval_sec = _validate_polling_interval(body.polling_interval_sec)

    db.commit()
    db.refresh(config)
    return _to_out(config)


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

    next_active = not config.is_active
    if next_active:
        other_active = _get_other_active_config(db, exclude_id=config.id)
        if other_active is not None:
            raise HTTPException(
                status_code=409,
                detail="Another active config already exists",
            )

    config.is_active = next_active
    db.commit()
    db.refresh(config)
    return _to_out(config)
