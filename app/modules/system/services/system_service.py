"""
System service — get_all_services_status 조합 전용 (facade thin wrapper)

각 서비스 클래스: NssmService, WorkerService, RedisService, CleanupStatsService
"""
from ..config import MANAGED_PROJECTS
from .nssm_service import NssmService
from .worker_service import WorkerService


class SystemService:
    """get_all_services_status — 각 서비스 결과를 프로젝트별로 조합"""

    def __init__(self):
        self._nssm = NssmService()
        self._worker = WorkerService()

    async def get_all_services_status(self) -> dict:
        """Get all services status grouped by project"""
        nssm_services = await self._nssm.get_nssm_services()
        startup_programs = await self._nssm.get_startup_programs()
        scheduled_tasks = await self._nssm.get_scheduled_tasks()
        worker_processes = await self._worker.get_worker_status()

        # Group by project
        projects = {}
        for project_name in MANAGED_PROJECTS.keys():
            projects[project_name] = {
                "nssm_services": [s for s in nssm_services if s.get("project") == project_name],
                "startup_programs": [s for s in startup_programs if s.get("project") == project_name],
                "scheduled_tasks": [s for s in scheduled_tasks if s.get("project") == project_name],
                "worker_processes": [s for s in worker_processes if s.get("project") == project_name]
            }

        return {"projects": projects}
