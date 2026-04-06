"""
쿠팡 여행상품 취소표 모니터링 모듈
"""

from typing import List, Type, Dict, Callable
from fastapi import APIRouter

from app.modules import ModuleInterface


class CoupangTravelModule(ModuleInterface):
    """쿠팡 여행상품 모니터링 모듈"""

    @property
    def name(self) -> str:
        return "coupang_travel"

    @property
    def display_name(self) -> str:
        return "쿠팡 여행"

    @property
    def api_prefix(self) -> str:
        return "/coupang"

    def get_router(self) -> APIRouter:
        from app.modules.coupang_travel.routes.monitor import router
        return router

    def get_worker_hooks(self) -> Dict[str, Callable]:
        return {}

    def get_models(self) -> List[Type]:
        from app.models.business import Business
        from app.models.biz_item import BizItem
        from app.models.monitor_schedule import MonitorSchedule

        return [Business, BizItem, MonitorSchedule]


module = CoupangTravelModule()

__all__ = ['CoupangTravelModule', 'module']
