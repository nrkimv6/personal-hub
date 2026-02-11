"""Auto Next Routes - 모든 라우터를 re-export"""

from fastapi import APIRouter

# 기본 라우터 생성
router = APIRouter(prefix="/api/v1/auto-next", tags=["auto-next"])

# 라우터 import 및 등록
from .tasks import router as tasks_router
from .stats import router as stats_router
from .runner import router as runner_router
from .logs import router as logs_router
from .plans import router as plans_router

router.include_router(tasks_router)
router.include_router(stats_router)
router.include_router(runner_router)
router.include_router(logs_router)
router.include_router(plans_router)

__all__ = ['router']
