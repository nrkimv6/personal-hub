"""
System dashboard API routes
Provides endpoints for querying and managing Windows services, startup programs, and scheduled tasks
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .services.nssm_service import NssmService
from .services.worker_service import WorkerService
from .services.redis_service import RedisService
from .services.cleanup_stats_service import CleanupStatsService
from .services.system_service import SystemService

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Service instances
_nssm = NssmService()
_worker = WorkerService()
_redis = RedisService()
_cleanup = CleanupStatsService()
_service = SystemService()  # get_all_services_status 전용


# ===== Read Operations (Phase 1) =====

@router.get("/services/status")
async def get_all_services_status(request: Request):
    """Get all services status grouped by project (cached)

    Returns:
        projects: 프로젝트별 서비스 상태
        collected_at: 마지막 수집 시각 (ISO 8601)
        collection_duration_ms: 수집 소요 시간 (ms)
    """
    collector = getattr(request.app.state, "system_cache_collector", None)
    if collector:
        return collector.get_cached_status()
    # fallback: 캐시 수집기가 없으면 직접 수집 (느림)
    return await _service.get_all_services_status()


@router.post("/services/refresh", status_code=202)
async def refresh_services_status(request: Request, background_tasks: BackgroundTasks):
    """백그라운드에서 상태 수집을 시작하고 즉시 반환 (202 Accepted)

    수집 완료 후 GET /services/status가 자동으로 새 캐시를 반환합니다.

    Returns:
        status: "refreshing"
        last_cached: 현재 캐시 수집 시각 (수집 전 마지막 값)
    """
    collector = getattr(request.app.state, "system_cache_collector", None)
    if not collector:
        raise HTTPException(status_code=503, detail="Cache collector not initialized")

    cached = collector.get_cached_status()
    background_tasks.add_task(collector.collect_and_cache)

    return {
        "status": "refreshing",
        "last_cached": cached.get("collected_at"),
    }


@router.get("/services/nssm")
async def get_nssm_services():
    """Get NSSM services list (filtered by prefix)"""
    return await _nssm.get_nssm_services()


@router.get("/services/startup")
async def get_startup_programs():
    """Get startup programs list (filtered by prefix)"""
    return await _nssm.get_startup_programs()


@router.get("/services/tasks")
async def get_scheduled_tasks():
    """Get scheduled tasks list (filtered by folder)"""
    return await _nssm.get_scheduled_tasks()


@router.get("/services/workers")
async def get_worker_status():
    """Get worker processes status"""
    return await _worker.get_worker_status()


# ===== Management Operations (Phase 2) =====

@router.post("/services/nssm/{name}/restart")
async def restart_nssm_service(name: str):
    """Restart an NSSM service"""
    result = await _nssm.restart_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/nssm/{name}/stop")
async def stop_nssm_service(name: str):
    """Stop an NSSM service"""
    result = await _nssm.stop_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/nssm/{name}/start")
async def start_nssm_service(name: str):
    """Start an NSSM service"""
    result = await _nssm.start_nssm_service(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.delete("/services/startup/{name}")
async def remove_startup_program(name: str):
    """Remove a startup program"""
    result = await _nssm.remove_startup_program(name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/services/tasks/{folder}/{name}/run")
async def run_scheduled_task(folder: str, name: str):
    """Run a scheduled task manually"""
    result = await _nssm.run_scheduled_task(folder, name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.delete("/services/tasks/{folder}/{name}")
async def unregister_scheduled_task(folder: str, name: str):
    """Unregister a scheduled task (requires admin)"""
    result = await _nssm.unregister_scheduled_task(folder, name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/workers/restart")
async def restart_workers():
    """Restart all worker processes (watchdog가 자동 재시작)"""
    result = await _worker.restart_worker("all")
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/workers/{name}/restart")
async def restart_single_worker(name: str):
    """Restart a single worker process by name"""
    result = await _worker.restart_worker(name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/services/infra/{name}/restart")
async def restart_infra(name: str):
    """Restart an infra tier process by name (via Redis infra:commands)"""
    result = await _worker.restart_infra(name)
    return result


@router.post("/services/watchdogs/stop")
async def stop_watchdogs():
    """Stop all watchdog processes"""
    result = await _worker.stop_watchdogs()
    return result


@router.post("/services/watchdogs/start")
async def start_watchdogs():
    """Start watchdog processes via Redis Command Listener"""
    result = await _worker.start_watchdogs()
    return result


# ===== Nightly Cleanup Stats =====

@router.get("/nightly-cleanup/stats")
async def get_nightly_cleanup_stats(days: int = 14):
    """Nightly done-cleanup 로그 파일에서 통계 조회

    Args:
        days: 조회할 최근 일수 (기본 14일)

    Returns:
        runs: 실행 이력 (날짜별)
        summary: 전체 요약
    """
    return await _cleanup.get_nightly_cleanup_stats(days)


# ===== Redis Operations =====

@router.get("/services/redis")
async def get_redis_status():
    """Redis 연결 상태 및 info 조회"""
    return await _redis.get_redis_status()


@router.post("/services/redis/restart")
async def restart_redis():
    """Redis 컨테이너 재시작 (podman-compose 경유)

    Note: Session 0 (NSSM)에서 실행 시 실패할 수 있음.
    실패 시 CLI에서 `scripts/services/browser_workers.py redis-restart` 사용.
    """
    result = await _redis.restart_redis()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result
