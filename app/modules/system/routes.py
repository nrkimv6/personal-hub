"""
System dashboard API routes
Provides endpoints for querying and managing Windows services, startup programs, and scheduled tasks
"""
from typing import Optional
from fastapi import APIRouter, HTTPException

from .services.system_service import SystemService
from .services.system_cache_collector import SystemCacheCollector

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Service instance
_service = SystemService()
_cache_collector: Optional[SystemCacheCollector] = None


def set_cache_collector(collector: SystemCacheCollector):
    """main.py에서 호출하여 collector 인스턴스 설정"""
    global _cache_collector
    _cache_collector = collector


# ===== Read Operations (Phase 1) =====

@router.get("/services/status")
async def get_all_services_status():
    """Get all services status grouped by project (cached)

    Returns:
        projects: 프로젝트별 서비스 상태
        collected_at: 마지막 수집 시각 (ISO 8601)
        collection_duration_ms: 수집 소요 시간 (ms)
    """
    if _cache_collector:
        return _cache_collector.get_cached_status()
    # fallback: 캐시 수집기가 없으면 직접 수집 (느림)
    return await _service.get_all_services_status()


@router.post("/services/refresh")
async def refresh_services_status():
    """즉시 상태 수집 후 반환

    Returns:
        projects: 프로젝트별 서비스 상태
        collected_at: 수집 시각 (ISO 8601)
        collection_duration_ms: 수집 소요 시간 (ms)
    """
    if not _cache_collector:
        raise HTTPException(status_code=503, detail="Cache collector not initialized")

    result = await _cache_collector.collect_and_cache()
    if result is None:
        raise HTTPException(status_code=503, detail="Collection in progress or failed")

    return result


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
    """Restart all worker processes (watchdog가 자동 재시작)"""
    result = await _service.restart_worker("all")
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/workers/{name}/restart")
async def restart_single_worker(name: str):
    """Restart a single worker process by name"""
    result = await _service.restart_worker(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/watchdogs/stop")
async def stop_watchdogs():
    """Stop all watchdog processes"""
    result = await _service.stop_watchdogs()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/watchdogs/start")
async def start_watchdogs():
    """Start watchdog processes via Redis Command Listener"""
    result = await _service.start_watchdogs()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


# ===== Redis Operations =====

@router.get("/services/redis")
async def get_redis_status():
    """Redis 연결 상태 및 info 조회"""
    return await _service.get_redis_status()


@router.post("/services/redis/restart")
async def restart_redis():
    """Redis 컨테이너 재시작 (podman-compose 경유)

    Note: Session 0 (NSSM)에서 실행 시 실패할 수 있음.
    실패 시 CLI에서 browser_workers.py redis-restart 사용.
    """
    result = await _service.restart_redis()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result
