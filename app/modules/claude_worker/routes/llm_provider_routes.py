"""Provider, defaults, and scheduler runtime LLM routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.claude_worker.services.llm_service import LLMService
from app.modules.claude_worker.services import provider_registry
from app.modules.claude_worker.routes.llm_schemas import (
    LLMDefaultConfig,
    LLMDefaultsResponse,
    LLMDefaultsUpdateRequest,
    SchedulerRuntimeCallerSummary,
    SchedulerRuntimeLatestRequest,
    SchedulerRuntimeProviderSummary,
    SchedulerRuntimeSummaryResponse,
)

router = APIRouter(tags=["llm"])

@router.get("/providers")
def get_llm_providers():
    """enabled 상태의 LLM Provider 목록 조회.

    Returns:
        [
          {
            "key": "claude",
            "display_name": "Claude",
            "default_model": "claude-opus-4-6",
            "models": ["claude-opus-4-6", "claude-sonnet-4-6"],
            "supports_chat": true,
            "supports_quota_pause": true,
            "enabled": true,
            "executor_key": "claude"
          },
          ...
        ]
    """
    return [
        {
            "key": p.key,
            "display_name": p.display_name,
            "default_model": p.default_model,
            "models": p.models,
            "supports_chat": p.supports_chat,
            "supports_quota_pause": p.supports_quota_pause,
            "enabled": p.enabled,
            "executor_key": p.executor_key,
        }
        for p in provider_registry.list_enabled()
    ]


@router.get("/defaults", response_model=LLMDefaultsResponse)
def get_llm_defaults(db: Session = Depends(get_db)):
    """LLM 기본 provider/model 설정 조회."""
    service = LLMService(db)
    defaults = service.load_llm_defaults()
    return LLMDefaultsResponse(
        global_default=LLMDefaultConfig(**defaults.get("global_default", {"provider": "claude", "model": ""})),
        caller_defaults={k: LLMDefaultConfig(**v) for k, v in defaults.get("caller_defaults", {}).items()},
        supported_providers=service.get_supported_providers(),
        known_caller_types=service.get_known_caller_types(),
    )


@router.get("/scheduler-runtime-summary", response_model=SchedulerRuntimeSummaryResponse)
def get_scheduler_runtime_summary(
    recent_limit: int = Query(50, ge=1, le=200, description="집계할 최근 scheduler 요청 수"),
    db: Session = Depends(get_db),
):
    """최근 scheduler 요청의 실제 provider/model 집계 조회."""
    service = LLMService(db)
    summary = service.get_scheduler_runtime_summary(recent_limit=recent_limit)
    return SchedulerRuntimeSummaryResponse(
        recent_limit=summary["recent_limit"],
        total_requests=summary["total_requests"],
        provider_summary=[SchedulerRuntimeProviderSummary(**item) for item in summary["provider_summary"]],
        caller_summary=[SchedulerRuntimeCallerSummary(**item) for item in summary["caller_summary"]],
        latest_request=(
            SchedulerRuntimeLatestRequest(**summary["latest_request"])
            if summary.get("latest_request")
            else None
        ),
    )


@router.put("/defaults", response_model=LLMDefaultsResponse)
def update_llm_defaults(
    body: LLMDefaultsUpdateRequest,
    db: Session = Depends(get_db),
):
    """LLM 기본 provider/model 설정 저장."""
    service = LLMService(db)
    try:
        saved = service.save_llm_defaults(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return LLMDefaultsResponse(
        global_default=LLMDefaultConfig(**saved.get("global_default", {"provider": "claude", "model": ""})),
        caller_defaults={k: LLMDefaultConfig(**v) for k, v in saved.get("caller_defaults", {}).items()},
        supported_providers=service.get_supported_providers(),
        known_caller_types=service.get_known_caller_types(),
    )
