"""Claude Worker 라우트."""

from app.modules.claude_worker.routes.llm_routes import router
from app.modules.claude_worker.routes import profile_routes, schedule_profile_policy_routes

# profile_routes.router (prefix 없음)를 llm_routes.router (/api/v1/llm) 아래에 마운트
# → 최종 URL: /api/v1/llm/profiles/*
router.include_router(profile_routes.router)
router.include_router(schedule_profile_policy_routes.router)

__all__ = ["router"]
