"""
System dashboard API routes
Provides endpoints for querying and managing Windows services, startup programs, and scheduled tasks
"""
from fastapi import APIRouter, HTTPException

from .services.system_service import SystemService

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Service instance
_service = SystemService()


# ===== Read Operations (Phase 1) =====

@router.get("/services/status")
async def get_all_services_status():
    """Get all services status grouped by project"""
    return await _service.get_all_services_status()


@router.get("/services/nssm")
async def get_nssm_services():
    """Get NSSM services list (filtered by prefix)"""
    return await _service.get_nssm_services()


@router.get("/services/startup")
async def get_startup_programs():
    """Get startup programs list (filtered by prefix)"""
    return await _service.get_startup_programs()


@router.get("/services/tasks")
async def get_scheduled_tasks():
    """Get scheduled tasks list (filtered by folder)"""
    return await _service.get_scheduled_tasks()


@router.get("/services/workers")
async def get_worker_status():
    """Get worker processes status"""
    return await _service.get_worker_status()


# ===== Management Operations (Phase 2) =====

@router.post("/services/nssm/{name}/restart")
async def restart_nssm_service(name: str):
    """Restart an NSSM service"""
    result = await _service.restart_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/nssm/{name}/stop")
async def stop_nssm_service(name: str):
    """Stop an NSSM service"""
    result = await _service.stop_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/nssm/{name}/start")
async def start_nssm_service(name: str):
    """Start an NSSM service"""
    result = await _service.start_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.delete("/services/startup/{name}")
async def remove_startup_program(name: str):
    """Remove a startup program"""
    result = await _service.remove_startup_program(name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/services/tasks/{folder}/{name}/run")
async def run_scheduled_task(folder: str, name: str):
    """Run a scheduled task manually"""
    result = await _service.run_scheduled_task(folder, name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.delete("/services/tasks/{folder}/{name}")
async def unregister_scheduled_task(folder: str, name: str):
    """Unregister a scheduled task (requires admin)"""
    result = await _service.unregister_scheduled_task(folder, name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/workers/restart")
async def restart_workers():
    """Restart all worker processes"""
    result = await _service.restart_worker("all")
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result
