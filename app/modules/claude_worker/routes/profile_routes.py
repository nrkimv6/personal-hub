"""LLM Profile 엔드포인트 — llm_routes.py에서 분리."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import require_admin, UserInfo

router = APIRouter(tags=["llm"])


# ========== Profile Schemas ==========

class LLMProfileConfig(BaseModel):
    engine: str
    name: str
    config_dir: Optional[str] = None
    extra_env: dict[str, str] = Field(default_factory=dict)


class LLMProfilesResponse(BaseModel):
    selected: dict[str, str]
    profiles: List[LLMProfileConfig]
    supported_engines: List[str]


class LLMProfilesUpdateRequest(BaseModel):
    selected: dict[str, str] = Field(default_factory=dict)
    profiles: List[LLMProfileConfig] = Field(default_factory=list)


class LLMProfileSelectRequest(BaseModel):
    name: str


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

    # payload 조립
    launch_payload = json.dumps({
        "action": "launch-cli",
        "engine": engine,
        "name": name,
        "config_dir": profile.get("config_dir"),
        "extra_env": profile.get("extra_env") or {},
        "engine_cmd": engine_cmd,
        "env_key": ENGINE_ENV_KEYS.get(engine),
    }, ensure_ascii=False)

    # 이전 결과 비우기 (race condition 방지)
    await redis_client.delete("worker:launch-cli:results")

    # 명령 전송
    await redis_client.lpush("worker:launch-cli", launch_payload)

    # 결과 대기
    result = await redis_client.brpop("worker:launch-cli:results", timeout=10)

    if result is None:
        return {"status": "timeout", "message": "명령 전송됨, 리스너 응답 대기 타임아웃"}

    _, result_data = result
    result_json = json.loads(result_data if isinstance(result_data, str) else result_data.decode())
    return result_json
