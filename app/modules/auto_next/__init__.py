"""Auto Next Module - auto-next Python 시스템 통합"""

from app.modules import ModuleInterface
from fastapi import APIRouter
from typing import Dict, Callable, List, Type


class AutoNextModule(ModuleInterface):
    """auto-next 모듈"""

    @property
    def name(self) -> str:
        return 'auto_next'

    @property
    def display_name(self) -> str:
        return 'Auto Next'

    @property
    def api_prefix(self) -> str:
        return '/auto-next'

    def get_router(self) -> APIRouter:
        """FastAPI 라우터 반환"""
        from app.modules.auto_next.routes import router
        return router

    def get_worker_hooks(self) -> Dict[str, Callable]:
        """워커 훅 함수들 반환 (사용하지 않음)"""
        return {}

    def get_models(self) -> List[Type]:
        """SQLAlchemy 모델 클래스들 반환 (SQLite 직접 접근으로 사용하지 않음)"""
        return []


# 모듈 인스턴스
module = AutoNextModule()

__all__ = ['module']
