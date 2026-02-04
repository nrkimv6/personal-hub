"""모바일 크롤링 라우터"""
from fastapi import APIRouter
from .mobile_proxy import router as mobile_proxy_router

# 메인 라우터
router = APIRouter(prefix="/mobile", tags=["mobile"])
router.include_router(mobile_proxy_router)

__all__ = ["router"]
