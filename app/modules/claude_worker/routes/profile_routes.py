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
def launch_cli(
    engine: str,
    name: str,
    admin: UserInfo = Depends(require_admin),
):
    """CLI 직접 실행 (admin 전용) — 해당 profile env 로 새 콘솔 창을 띄운다.

    로그인 등 대화형 세션 목적. admin FastAPI app 에만 include_router 되므로
    public(8000)에서는 접근 불가.
    """
    import subprocess
    import sys
    from app.modules.claude_worker.services.profile_env import build_cli_env
    from app.modules.claude_worker.services.profile_store import load_profiles

    if engine not in _ENGINE_CLI_COMMANDS:
        raise HTTPException(status_code=422, detail=f"unsupported engine: {engine!r}")

    # profile 존재 검증
    payload = load_profiles()
    profile_names = [p["name"] for p in payload.get("profiles", []) if p.get("engine") == engine]
    if name not in profile_names:
        raise HTTPException(status_code=404, detail=f"profile {name!r} not found for engine {engine!r}")

    engine_cmd = _ENGINE_CLI_COMMANDS[engine]
    env = build_cli_env(engine)

    if sys.platform == "win32":
        # CREATE_NEW_CONSOLE 으로 독립 콘솔 창 생성 (start 명령 사용 금지 — 이중 창 방지)
        subprocess.Popen(
            ["cmd", "/k", engine_cmd],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
    else:
        subprocess.Popen(["xterm", "-e", engine_cmd], env=env, close_fds=True)

    return {"status": "launched", "engine": engine, "profile": name}
