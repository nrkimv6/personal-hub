"""Quota registry administration routes."""

from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.claude_worker.services import provider_registry
from app.shared.llm_registry import (
    NoAvailableModelError,
    load_quota_state,
    load_registry,
    pick_model,
    report_quota,
    save_quota_state,
    _now_kst,
)

router = APIRouter(tags=["llm"])

class QuotaReportRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    weekly_used_pct: Optional[float] = None
    delta_weekly_pct: Optional[float] = None
    weekly_reset_at: Optional[datetime] = None
    short_cooldown_minutes: Optional[int] = None

    def validate_exclusive(self):
        if self.weekly_used_pct is not None and self.delta_weekly_pct is not None:
            raise ValueError("weekly_used_pct와 delta_weekly_pct는 동시에 지정할 수 없습니다.")


class QuotaClearRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


@router.get("/quota")
async def get_quota():
    """현재 quota 상태 + step별 picker 결과 반환."""
    try:
        now = _now_kst()
        state = load_quota_state(apply_decay_in_memory=True, now=now)
        registry = load_registry()

        entries = {
            key: {
                "weekly_used_pct": quota.weekly_used_pct,
                "weekly_reset_at": quota.weekly_reset_at.isoformat() if quota.weekly_reset_at else None,
                "short_cooldown_until": quota.short_cooldown_until.isoformat() if quota.short_cooldown_until else None,
                "updated_at": quota.updated_at.isoformat() if quota.updated_at else None,
            }
            for key, quota in state.items()
        }

        picker_by_step: Dict[str, Optional[dict]] = {}
        for step in registry:
            try:
                p, m = pick_model(step, oneshot=False, now=now)
                picker_by_step[step] = {"provider": p, "model": m}
            except NoAvailableModelError:
                picker_by_step[step] = None

        return {"entries": entries, "picker_by_step": picker_by_step}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quota/report")
async def report_quota_endpoint(body: QuotaReportRequest):
    """quota 상태 수동 보고/갱신."""
    try:
        body.validate_exclusive()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not provider_registry.is_supported(body.provider):
        raise HTTPException(status_code=400, detail=f"지원되지 않는 provider: {body.provider}")

    try:
        report_quota(
            provider=body.provider,
            model=body.model,
            weekly_used_pct=body.weekly_used_pct,
            delta_weekly_pct=body.delta_weekly_pct,
            weekly_reset_at=body.weekly_reset_at,
            short_cooldown_minutes=body.short_cooldown_minutes,
            source="manual_api",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 갱신 후 현재 state 반환
    state = load_quota_state(apply_decay_in_memory=True)
    return {
        "ok": True,
        "entries": {
            key: {
                "weekly_used_pct": q.weekly_used_pct,
                "weekly_reset_at": q.weekly_reset_at.isoformat() if q.weekly_reset_at else None,
                "short_cooldown_until": q.short_cooldown_until.isoformat() if q.short_cooldown_until else None,
            }
            for key, q in state.items()
        },
    }


@router.post("/quota/clear")
async def clear_quota(body: QuotaClearRequest):
    """quota 상태 초기화 (테스트/수동 복구용)."""
    try:
        state = load_quota_state(apply_decay_in_memory=False)

        if body.provider is None:
            # 전체 리셋
            cleared_keys = list(state.keys())
            state = {}
        elif body.model is None:
            # provider 하위 전체
            cleared_keys = [k for k in state if k.startswith(f"{body.provider}/")]
            for k in cleared_keys:
                del state[k]
        else:
            key = f"{body.provider}/{body.model}"
            cleared_keys = [key] if key in state else []
            state.pop(key, None)

        save_quota_state(state)
        return {"ok": True, "cleared": cleared_keys}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
