"""Shared schemas and response helpers for LLM routes."""

import json
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.modules.claude_worker.services import provider_registry

LLM_PENDING_BLOCK_REASONS = {
    "all_paused_by_quota",
    "outside_window",
    "schedule_policy_off",
    "profile_claim_conflict",
    "no_enabled_profile",
}

class LLMRequestCreate(BaseModel):
    caller_type: str
    caller_id: str
    prompt: str
    requested_by: str = "api"
    request_source: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    queue_name: str = "utility"
    cli_options: Optional[dict] = None
    mode: str = "single"

    @validator("provider")
    def validate_provider(cls, v):
        if v is None:
            return v
        if not provider_registry.is_supported(v):
            raise ValueError(f"지원되지 않는 provider: {v}")
        return v


class LLMRequestResponse(BaseModel):
    id: int
    caller_type: str
    caller_id: str
    status: str
    requested_by: Optional[str] = None
    request_source: Optional[str] = None
    provider: str = "claude"
    model: str = ""
    mode: str = "single"
    queue_name: str = "utility"
    requested_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    pending_block_reason: Optional[str] = None
    retry_count: int = 0
    prompt: Optional[str] = None
    cli_options: Optional[dict] = None

    class Config:
        from_attributes = True


class LLMRequestUpdate(BaseModel):
    cli_options: Optional[dict] = None
    prompt: Optional[str] = None


class LLMRequestDetailResponse(LLMRequestResponse):
    """상세 조회용 응답 (raw_response 포함)."""
    raw_response: Optional[str] = None


class LLMRequestListResponse(BaseModel):
    items: List[LLMRequestResponse]
    total: int
    page: int
    page_size: int
    pages: int


class LLMWorkerStatusResponse(BaseModel):
    status: str
    worker_id: Optional[str] = None
    state: Optional[str] = None
    processed_count: Optional[int] = None
    message: Optional[str] = None


class LLMStatsResponse(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int


class LLMBootstrapResponse(BaseModel):
    list: LLMRequestListResponse
    stats: LLMStatsResponse
    queue_stats: Dict[str, Dict[str, int]]
    worker_status: LLMWorkerStatusResponse


class BatchRetryRequest(BaseModel):
    request_ids: List[int]


class BatchDeleteRequest(BaseModel):
    request_ids: List[int]
    hard_delete: bool = False


class HistoryStatsResponse(BaseModel):
    data: List[dict]
    summary: dict


class LLMDefaultConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = ""


class LLMDefaultsResponse(BaseModel):
    global_default: LLMDefaultConfig
    caller_defaults: dict[str, LLMDefaultConfig]
    supported_providers: List[str]
    known_caller_types: List[str]


class LLMDefaultsUpdateRequest(BaseModel):
    global_default: LLMDefaultConfig
    caller_defaults: dict[str, LLMDefaultConfig] = Field(default_factory=dict)


class SchedulerRuntimeProviderSummary(BaseModel):
    provider: str
    model: str
    count: int
    latest_requested_at: Optional[datetime] = None
    caller_types: List[str] = Field(default_factory=list)


class SchedulerRuntimeCallerSummary(BaseModel):
    caller_type: str
    provider: str
    model: str
    count: int
    latest_requested_at: Optional[datetime] = None


class SchedulerRuntimeLatestRequest(BaseModel):
    id: int
    caller_type: str
    caller_id: str
    provider: str
    model: str
    requested_at: Optional[datetime] = None
    requested_by: Optional[str] = None
    request_source: Optional[str] = None


class SchedulerRuntimeSummaryResponse(BaseModel):
    recent_limit: int
    total_requests: int
    provider_summary: List[SchedulerRuntimeProviderSummary]
    caller_summary: List[SchedulerRuntimeCallerSummary]
    latest_request: Optional[SchedulerRuntimeLatestRequest] = None

def _parse_json_field(value):
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _to_response(request, include_raw: bool = False) -> LLMRequestResponse:
    """LLMRequest를 LLMRequestResponse로 변환.

    Args:
        request: LLMRequest 모델 인스턴스
        include_raw: True면 raw_response 포함 (상세 조회용)
    """
    if isinstance(request, dict):
        result = _parse_json_field(request.get("result"))
        cli_options = _parse_json_field(request.get("cli_options"))
        fields = dict(
            id=request["id"],
            caller_type=request["caller_type"],
            caller_id=request["caller_id"],
            status=request["status"],
            requested_by=request.get("requested_by"),
            request_source=request.get("request_source"),
            provider=request.get("provider", "claude"),
            model=request.get("model", ""),
            mode=request.get("mode", "single"),
            queue_name=request.get("queue_name", "utility"),
            requested_at=request.get("requested_at"),
            processed_at=request.get("processed_at"),
            result=result,
            error_message=request.get("error_message"),
            pending_block_reason=(
                request.get("error_message")
                if request.get("status") == "pending" and request.get("error_message") in LLM_PENDING_BLOCK_REASONS
                else None
            ),
            retry_count=request.get("retry_count", 0),
            prompt=request.get("prompt"),
            cli_options=cli_options,
        )
    else:
        result = _parse_json_field(request.result)
        fields = dict(
            id=request.id,
            caller_type=request.caller_type,
            caller_id=request.caller_id,
            status=request.status,
            requested_by=request.requested_by,
            request_source=request.request_source,
            provider=getattr(request, "provider", "claude"),
            model=getattr(request, "model", ""),
            mode=getattr(request, "mode", "single"),
            queue_name=getattr(request, "queue_name", "utility"),
            requested_at=request.requested_at,
            processed_at=request.processed_at,
            result=result,
            error_message=request.error_message,
            pending_block_reason=(
                request.error_message
                if request.status == "pending" and request.error_message in LLM_PENDING_BLOCK_REASONS
                else None
            ),
            retry_count=request.retry_count,
            prompt=request.prompt,
            cli_options=_parse_json_field(request.cli_options),
        )

    if include_raw:
        fields["raw_response"] = request.get("raw_response") if isinstance(request, dict) else getattr(request, "raw_response", None)
        return LLMRequestDetailResponse(**fields)

    return LLMRequestResponse(**fields)
