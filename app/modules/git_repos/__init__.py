"""Git Repository Status Manager 모듈."""

from app.modules import ModuleInterface
from fastapi import APIRouter
from typing import Dict, Callable, List, Type


class GitReposModule(ModuleInterface):
    """Git 레포지토리 관리 모듈"""

    @property
    def name(self) -> str:
        return 'git_repos'

    @property
    def display_name(self) -> str:
        return 'Git 레포지토리'

    @property
    def api_prefix(self) -> str:
        return '/git-repos'

    def get_router(self) -> APIRouter:
        from app.modules.git_repos.routes import router
        return router

    def get_worker_hooks(self) -> Dict[str, Callable]:
        return {}

    def get_models(self) -> List[Type]:
        from app.modules.git_repos.models import GitRepo, GitOperationLog
        return [GitRepo, GitOperationLog]


module = GitReposModule()

__all__ = ['module']
