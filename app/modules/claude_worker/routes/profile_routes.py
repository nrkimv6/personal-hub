"""LLM Profile 엔드포인트 — llm_routes.py에서 분리."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_admin, UserInfo
from app.database import get_db

router = APIRouter(tags=["llm"])


# ========== Profile Schemas ==========

class LLMProfileConfig(BaseModel):
    engine: str
    name: str
    config_dir: Optional[str] = None
    extra_env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = 0
    capacity: int = 1
    last_quota_pause_until: Optional[datetime] = None
    last_reset_at: Optional[datetime] = None
    last_state: Optional[str] = None
    last_error_summary: Optional[str] = None


class LLMProfilesResponse(BaseModel):
    selected: dict[str, str]
    profiles: List[LLMProfileConfig]
    supported_engines: List[str]


class LLMProfilesUpdateRequest(BaseModel):
    selected: dict[str, str] = Field(default_factory=dict)
    profiles: List[LLMProfileConfig] = Field(default_factory=list)


class LLMProfileSelectRequest(BaseModel):
    name: str


class LLMProfilePauseRequest(BaseModel):
    retry_after_ms: int = Field(default=60 * 60 * 1000, ge=1000)
    reason: str = "manual profile pause"


class LLMProfileStatusItem(BaseModel):
    engine: str
    profile_name: str
    state: str
    quota_reset_at: Optional[datetime] = None
    next_allowed_at: Optional[datetime] = None
    blocked_request_count: int = 0
    processing_count: int = 0
    capacity: int = 1
    last_error_summary: Optional[str] = None
    priority: int = 0


class LLMProfileAssignmentItem(BaseModel):
    request_id: int
    engine: str
    profile_name: str
    selected_at: datetime
    released_at: Optional[datetime] = None
    stop_reason: Optional[str] = None
    error_summary: Optional[str] = None


# ========== Profile Endpoints ==========

@router.get("/profiles", response_model=LLMProfilesResponse)
def get_llm_profiles():
    """LLM engine profile 목록 조회."""
    from app.modules.claude_worker.services.profile_store import load_profiles, SUPPORTED_ENGINES
    payload = load_profiles()
    return LLMProfilesResponse(
        selected=payload.get("selected", {}),
        profiles=[LLMProfileConfig(**p) for p in payload.get("profiles", [])],
        supported_engines=sorted(SUPPORTED_ENGINES),
    )


@router.put("/profiles", response_model=LLMProfilesResponse)
def update_llm_profiles(body: LLMProfilesUpdateRequest):
    """LLM engine profile 저장 (전체 upsert)."""
    from app.modules.claude_worker.services.profile_store import save_profiles, SUPPORTED_ENGINES
    try:
        payload = {
            "selected": body.selected,
            "profiles": [p.model_dump() for p in body.profiles],
        }
        saved = save_profiles(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return LLMProfilesResponse(
        selected=saved.get("selected", {}),
        profiles=[LLMProfileConfig(**p) for p in saved.get("profiles", [])],
        supported_engines=sorted(SUPPORTED_ENGINES),
    )


@router.post("/profiles/{engine}/select", response_model=LLMProfilesResponse)
def select_llm_profile(engine: str, body: LLMProfileSelectRequest):
    """특정 engine 의 선택 profile 변경."""
    from app.modules.claude_worker.services.profile_store import select, load_profiles, SUPPORTED_ENGINES
    try:
        saved = select(engine, body.name)
    except ValueError as e:
        code = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e))
    return LLMProfilesResponse(
        selected=saved.get("selected", {}),
        profiles=[LLMProfileConfig(**p) for p in saved.get("profiles", [])],
        supported_engines=sorted(SUPPORTED_ENGINES),
    )


@router.get("/profiles/status", response_model=List[LLMProfileStatusItem])
def get_llm_profile_status(db: Session = Depends(get_db)):
    """profile별 capacity/status summary."""
    from app.modules.claude_worker.services.execution_window_service import LLMExecutionWindowService
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.profile_store import list_profiles
    from app.modules.claude_worker.services.profile_claim_service import ProfileClaimService
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    quota = LLMQuotaService(LLMRequestRepository(db), LLMWorkerRepository(db), db)
    claims = ProfileClaimService(db)
    window = LLMExecutionWindowService().decide()
    rows: list[LLMProfileStatusItem] = []
    for profile in list_profiles():
        state = "available"
        quota_reset_at = quota.get_profile_quota_pause(profile.engine, profile.name)
        processing_count = claims.active_count(profile.engine, profile.name)
        if not profile.enabled:
            state = "disabled"
        elif not window.allowed:
            state = "paused_by_window"
        elif quota.get_provider_quota_pause(profile.engine) or quota_reset_at:
            state = "paused_by_quota"
        elif processing_count >= max(1, int(profile.capacity or 1)):
            state = "processing"
        rows.append(
            LLMProfileStatusItem(
                engine=profile.engine,
                profile_name=profile.name,
                state=state,
                quota_reset_at=quota_reset_at,
                next_allowed_at=window.next_allowed_at if state == "paused_by_window" else None,
                blocked_request_count=quota.get_blocked_pending_count(profile.engine) if state == "paused_by_quota" else 0,
                processing_count=processing_count,
                capacity=max(1, int(profile.capacity or 1)),
                last_error_summary=profile.last_error_summary,
                priority=profile.priority,
            )
        )
    return rows


@router.get("/profiles/{engine}/{name}/assignments", response_model=List[LLMProfileAssignmentItem])
def list_llm_profile_assignments(
    engine: str,
    name: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    from app.modules.claude_worker.models.llm_request import LLMProfileAssignment

    rows = (
        db.query(LLMProfileAssignment)
        .filter(LLMProfileAssignment.engine == engine, LLMProfileAssignment.profile_name == name)
        .order_by(LLMProfileAssignment.selected_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [
        LLMProfileAssignmentItem(
            request_id=row.request_id,
            engine=row.engine,
            profile_name=row.profile_name,
            selected_at=row.selected_at,
            released_at=row.released_at,
            stop_reason=row.stop_reason,
            error_summary=row.error_summary,
        )
        for row in rows
    ]


@router.post("/profiles/{engine}/{name}/pause")
def pause_llm_profile(engine: str, name: str, body: LLMProfilePauseRequest, db: Session = Depends(get_db)):
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    try:
        paused_until = LLMQuotaService(
            LLMRequestRepository(db),
            LLMWorkerRepository(db),
            db,
        ).set_profile_quota_pause(engine, name, body.retry_after_ms, body.reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"paused_until": paused_until}


@router.delete("/profiles/{engine}/{name}/pause")
def resume_llm_profile(engine: str, name: str, db: Session = Depends(get_db)):
    from app.modules.claude_worker.services.llm_quota_service import LLMQuotaService
    from app.modules.claude_worker.services.repositories import LLMRequestRepository, LLMWorkerRepository

    ok = LLMQuotaService(
        LLMRequestRepository(db),
        LLMWorkerRepository(db),
        db,
    ).clear_profile_quota_pause(engine, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"profile {name!r} not found for engine {engine!r}")
    return {"ok": True}


@router.delete("/profiles/{engine}/{name}", response_model=LLMProfilesResponse)
def delete_llm_profile(engine: str, name: str):
    """profile 삭제. selected 이던 경우 default 로 fallback."""
    from app.modules.claude_worker.services.profile_store import delete, load_profiles, SUPPORTED_ENGINES
    try:
        saved = delete(engine, name)
    except ValueError as e:
        code = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e))
    return LLMProfilesResponse(
        selected=saved.get("selected", {}),
        profiles=[LLMProfileConfig(**p) for p in saved.get("profiles", [])],
        supported_engines=sorted(SUPPORTED_ENGINES),
    )


_ENGINE_CLI_COMMANDS: dict[str, str] = {
    "claude": "claude",
    "gemini": "gemini",
}


@router.post("/profiles/{engine}/{name}/launch-cli")
async def launch_cli(
    engine: str,
    name: str,
    admin: UserInfo = Depends(require_admin),
):
    """CLI 직접 실행 (admin 전용) — Redis 릴레이로 Session 1에서 콘솔 창을 띄운다.

    Session 0(NSSM 서비스)에서 직접 subprocess 생성 시 창이 사용자 데스크톱에 보이지 않으므로,
    worker:launch-cli 큐에 명령을 넣어 Session 1의 worker-command-listener가 실행하도록 위임.
    로그인 등 대화형 세션 목적. admin FastAPI app 에만 include_router 되므로
    public(8000)에서는 접근 불가.
    """
    import json
    import uuid
    from app.shared.redis.client import RedisClient
    from app.modules.claude_worker.services.profile_env import ENGINE_ENV_KEYS
    from app.modules.claude_worker.services.profile_store import load_profiles

    if engine not in _ENGINE_CLI_COMMANDS:
        raise HTTPException(status_code=422, detail=f"unsupported engine: {engine!r}")

    # profile 존재 검증 + config_dir/extra_env 추출
    payload = load_profiles()
    profiles = payload.get("profiles", [])
    profile = next(
        (p for p in profiles if p.get("engine") == engine and p.get("name") == name),
        None,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail=f"profile {name!r} not found for engine {engine!r}")

    engine_cmd = _ENGINE_CLI_COMMANDS[engine]

    # Redis 클라이언트 획득
    redis_client = await RedisClient.get_client()
    if not redis_client:
        manual_cmd = f"set {ENGINE_ENV_KEYS.get(engine)}={profile.get('config_dir') or ''} && {engine_cmd}" if ENGINE_ENV_KEYS.get(engine) else engine_cmd
        return {
            "status": "redis_unavailable",
            "message": f"Redis 연결 없음. 수동으로 실행하세요: {manual_cmd}",
        }

    command_id = uuid.uuid4().hex
    result_key = f"worker:launch-cli:results:{command_id}"

    # payload 조립
    launch_payload = json.dumps({
        "action": "launch-cli",
        "command_id": command_id,
        "result_key": result_key,
        "engine": engine,
        "name": name,
        "config_dir": profile.get("config_dir"),
        "extra_env": profile.get("extra_env") or {},
        "engine_cmd": engine_cmd,
        "env_key": ENGINE_ENV_KEYS.get(engine),
    }, ensure_ascii=False)

    try:
        # 명령 전송
        await redis_client.lpush("worker:launch-cli", launch_payload)
    except Exception as e:
        # socket_timeout 초과, 연결 끊김 등 Redis 예외 → 500 방지
        return {"status": "error", "message": f"Redis 오류: {e}"}

    return {
        "success": True,
        "status": "accepted",
        "command_id": command_id,
        "result_key": result_key,
        "message": "CLI 실행 명령이 접수되었습니다.",
    }


@router.get("/profiles/{engine}/{name}/launch-cli/commands/{command_id}")
async def get_launch_cli_result(
    engine: str,
    name: str,
    command_id: str,
    admin: UserInfo = Depends(require_admin),
):
    """launch-cli 릴레이 결과를 non-blocking으로 조회한다."""
    import json
    from app.shared.redis.client import RedisClient

    redis_client = await RedisClient.get_client()
    if not redis_client:
        return {"status": "redis_unavailable", "message": "Redis 연결 없음"}

    result_key = f"worker:launch-cli:results:{command_id}"
    try:
        result_data = await redis_client.lindex(result_key, 0)
    except Exception as e:
        return {"status": "error", "message": f"Redis 오류: {e}"}

    if result_data is None:
        return {
            "success": True,
            "status": "pending",
            "command_id": command_id,
            "engine": engine,
            "profile": name,
        }

    result_json = json.loads(result_data if isinstance(result_data, str) else result_data.decode())
    return {
        "command_id": command_id,
        **result_json,
    }
