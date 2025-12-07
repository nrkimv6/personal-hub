"""
모듈 시스템

플랫폼별 독립 모듈을 관리합니다.
각 모듈은 ModuleInterface를 구현해야 합니다.
"""

from abc import ABC, abstractmethod
from typing import List, Type, Dict, Callable
from fastapi import APIRouter
import importlib
import pkgutil
import os


class ModuleInterface(ABC):
    """모든 플랫폼 모듈이 구현해야 하는 인터페이스"""

    @property
    @abstractmethod
    def name(self) -> str:
        """모듈 이름 (예: 'naver_booking')"""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """표시 이름 (예: '네이버 예약')"""
        pass

    @property
    @abstractmethod
    def api_prefix(self) -> str:
        """API 경로 prefix (예: '/naver')"""
        pass

    @abstractmethod
    def get_router(self) -> APIRouter:
        """FastAPI 라우터 반환"""
        pass

    @abstractmethod
    def get_worker_hooks(self) -> Dict[str, Callable]:
        """워커 훅 함수들 반환"""
        pass

    @abstractmethod
    def get_models(self) -> List[Type]:
        """SQLAlchemy 모델 클래스들 반환"""
        pass


def discover_modules() -> List[ModuleInterface]:
    """
    app/modules/ 디렉토리에서 모듈을 자동 검색합니다.

    각 모듈은 __init__.py에 `module` 변수로 ModuleInterface 인스턴스를 제공해야 합니다.
    """
    modules = []
    modules_dir = os.path.dirname(__file__)

    for item in os.listdir(modules_dir):
        module_path = os.path.join(modules_dir, item)

        # 디렉토리이면서, __로 시작하지 않고, _template이 아닌 경우
        if (os.path.isdir(module_path) and
            not item.startswith('_') and
            not item.startswith('.')):

            try:
                # 모듈 import
                module_pkg = importlib.import_module(f"app.modules.{item}")

                # module 변수 확인
                if hasattr(module_pkg, 'module'):
                    mod_instance = getattr(module_pkg, 'module')
                    if isinstance(mod_instance, ModuleInterface):
                        modules.append(mod_instance)
            except ImportError as e:
                # 모듈 로드 실패 시 로깅
                import logging
                logging.getLogger(__name__).warning(
                    f"모듈 로드 실패: {item} - {str(e)}"
                )

    return modules


__all__ = ['ModuleInterface', 'discover_modules']
