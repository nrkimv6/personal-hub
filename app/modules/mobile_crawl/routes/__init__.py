"""모바일 크롤링 라우터"""
from fastapi import APIRouter
from .mobile_proxy import router as mobile_proxy_router
from .targets import router as targets_router
from .items import router as items_router

# 메인 라우터
router = APIRouter(prefix="/mobile", tags=["mobile"])
router.include_router(mobile_proxy_router)
router.include_router(targets_router)
router.include_router(items_router)

__all__ = ["router"]
