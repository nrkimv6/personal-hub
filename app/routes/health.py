"""
서비스 헬스 상태 API 엔드포인트

- 모든 서비스 헬스 상태 조회
- 수동 헬스 체크 트리거
- 최근 알림 조회
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Optional
from pydantic import BaseModel

from app.core.config import logger

router = APIRouter(
    prefix="/health",
    tags=["health"]
)


class ServiceHealthResponse(BaseModel):
    """개별 서비스 헬스 상태"""
    name: str
    status: str  # healthy | unhealthy | unknown
    last_check: str
    failure_count: int
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    pid: Optional[int] = None
    expected_port: Optional[int] = None
    actual_port_owner: Optional[int] = None


class RecentAlertResponse(BaseModel):
    """최근 알림"""
    timestamp: str
    type: str  # failure | recovery
    service: str
    message: str
    check_type: str  # PID | HTTP


class HealthStatusResponse(BaseModel):
    """전체 헬스 상태 응답"""
    enabled: bool
    services: dict
    recent_alerts: list


@router.get("/status", response_model=HealthStatusResponse)
async def get_health_status(request: Request):
    """
    모든 서비스 헬스 상태를 조회합니다.

    헬스 모니터가 활성화되어 있어야 상태를 조회할 수 있습니다.
    """
    from app.core.config import settings

    if not settings.HEALTH_MONITOR_ENABLED:
        return HealthStatusResponse(
            enabled=False,
            services={},
            recent_alerts=[]
        )

    monitor = getattr(request.app.state, "health_monitor", None)
    if not monitor:
        return HealthStatusResponse(
            enabled=True,
            services={},
            recent_alerts=[]
        )

    return HealthStatusResponse(
        enabled=True,
        services=monitor.get_all_services_status(),
        recent_alerts=monitor.get_recent_alerts(limit=20)
    )


@router.post("/check")
async def trigger_health_check(request: Request):
    """
    수동으로 헬스 체크를 트리거합니다.

    PID+포트 체크와 HTTP 체크를 모두 수행하고 결과를 반환합니다.
    """
    from app.core.config import settings

    if not settings.HEALTH_MONITOR_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Health monitor is disabled"
        )

    monitor = getattr(request.app.state, "health_monitor", None)
    if not monitor:
        raise HTTPException(
            status_code=503,
            detail="Health monitor not initialized"
        )

    try:
        # PID+포트 체크
        pid_results = await monitor.check_all_pid_ports()

        # HTTP 체크
        http_results = await monitor.check_all_http_endpoints()

        # 결과를 서비스 상태에 반영
        for health in pid_results + http_results:
            monitor.services[health.name] = health

        return {
            "status": "success",
            "pid_check_results": [h.to_dict() for h in pid_results],
            "http_check_results": [h.to_dict() for h in http_results]
        }
    except Exception as e:
        logger.error(f"수동 헬스 체크 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts")
async def get_recent_alerts(request: Request, limit: int = 20):
    """
    최근 알림 목록을 조회합니다.

    Args:
        limit: 조회할 알림 개수 (기본값: 20)
    """
    from app.core.config import settings

    if not settings.HEALTH_MONITOR_ENABLED:
        return {"alerts": []}

    monitor = getattr(request.app.state, "health_monitor", None)
    if not monitor:
        return {"alerts": []}

    return {
        "alerts": monitor.get_recent_alerts(limit=limit)
    }
