"""카카오 모니터 라우트"""
from .config_routes import router as config_router
from .keyword_routes import router as keyword_router
from .history_routes import router as history_router
from .worker_routes import router as worker_router

from fastapi import APIRouter

router = APIRouter()
router.include_router(config_router)
router.include_router(keyword_router)
router.include_router(history_router)
router.include_router(worker_router)

__all__ = ["router"]
