"""Dev Runner Routes - 모든 라우터를 re-export"""

from fastapi import APIRouter

# 기본 라우터 생성
router = APIRouter(prefix="/api/v1/dev-runner", tags=["dev-runner"])

# 라우터 import 및 등록
from .tasks import router as tasks_router
from .runner import router as runner_router
from .logs import router as logs_router
from .plans import router as plans_router
from .engines import router as engines_router
from .events import router as events_router
from .settings import router as settings_router
from .workflows import router as workflows_router
from .worktrees import router as worktrees_router
from .daily_reports import router as daily_reports_router

router.include_router(tasks_router)
router.include_router(runner_router)
router.include_router(logs_router)
router.include_router(plans_router)
router.include_router(engines_router, prefix="/engines")
router.include_router(events_router)
router.include_router(settings_router, prefix="/settings")
router.include_router(workflows_router, prefix="/workflows")
router.include_router(worktrees_router, prefix="/worktrees")
router.include_router(daily_reports_router)

__all__ = ['router']
