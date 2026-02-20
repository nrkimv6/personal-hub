"""Dev Runner Module - plan-runner Python 시스템 통합"""

from app.modules import ModuleInterface
from fastapi import APIRouter
from typing import Dict, Callable, List, Type


class DevRunnerModule(ModuleInterface):
    """dev-runner 모듈"""

    @property
    def name(self) -> str:
        return 'dev_runner'

    @property
    def display_name(self) -> str:
        return 'Dev Runner'

    @property
    def api_prefix(self) -> str:
        return '/plan-runner'

    def get_router(self) -> APIRouter:
        """FastAPI 라우터 반환"""
        from app.modules.dev_runner.routes import router
        return router

    def get_worker_hooks(self) -> Dict[str, Callable]:
        """워커 훅 함수들 반환 (사용하지 않음)"""
        return {}

    def get_models(self) -> List[Type]:
        """SQLAlchemy 모델 클래스들 반환 (SQLite 직접 접근으로 사용하지 않음)"""
        return []


# 모듈 인스턴스
module = DevRunnerModule()

__all__ = ['module']
