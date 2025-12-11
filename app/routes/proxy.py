"""
프록시 상태 API 라우트
작성일: 2025-12-11

프록시 매니저 상태 조회 및 관리 API를 제공합니다.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from app.core.config import settings, logger
from app.services.proxy_manager import get_proxy_manager, init_proxy_manager, ProxyManager

router = APIRouter(prefix="/api/v1/proxy", tags=["proxy"])


@router.get("/status")
async def get_proxy_status() -> Dict[str, Any]:
    """
    프록시 매니저 상태를 조회합니다.

    Returns:
        - enabled: 프록시 설정 활성화 여부
        - initialized: 프록시 매니저 초기화 여부
        - total: 전체 프록시 수
        - active_pool: 활성 프록시 풀 크기
        - blacklisted: 블랙리스트 프록시 수
        - current: 현재 사용 중인 프록시
        - request_count: 총 요청 수
        - next_rotation_in: 다음 로테이션까지 남은 요청 수
    """
    proxy_manager = get_proxy_manager()

    if proxy_manager is None:
        return {
            "enabled": settings.PROXY_ENABLED,
            "initialized": False,
            "message": "프록시 매니저가 초기화되지 않았습니다"
        }

    status = proxy_manager.get_status()
    status["enabled"] = settings.PROXY_ENABLED
    return status


@router.post("/initialize")
async def initialize_proxy() -> Dict[str, Any]:
    """
    프록시 매니저를 초기화합니다.

    설정에서 프록시가 비활성화되어 있어도 수동으로 초기화할 수 있습니다.
    """
    try:
        proxy_manager = await init_proxy_manager(
            enabled=True,
            rotation_interval=settings.PROXY_ROTATION_INTERVAL,
            max_active_pool=settings.PROXY_MAX_ACTIVE_POOL,
            connection_timeout=settings.PROXY_CONNECTION_TIMEOUT,
            blacklist_duration=settings.PROXY_BLACKLIST_DURATION,
        )

        if proxy_manager is None:
            raise HTTPException(
                status_code=500,
                detail="프록시 매니저 초기화 실패: 유효한 프록시가 없습니다"
            )

        return {
            "success": True,
            "message": "프록시 매니저가 초기화되었습니다",
            "status": proxy_manager.get_status()
        }

    except Exception as e:
        logger.error(f"프록시 초기화 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_proxy_pool() -> Dict[str, Any]:
    """
    프록시 풀을 새로고침합니다.

    프록시 목록을 다시 로드하고 품질 테스트를 수행합니다.
    """
    proxy_manager = get_proxy_manager()

    if proxy_manager is None:
        raise HTTPException(
            status_code=400,
            detail="프록시 매니저가 초기화되지 않았습니다. /initialize를 먼저 호출하세요."
        )

    try:
        # 파일 리로드 및 풀 새로고침
        await proxy_manager.check_and_reload()
        await proxy_manager.refresh_active_pool()

        return {
            "success": True,
            "message": "프록시 풀이 새로고침되었습니다",
            "status": proxy_manager.get_status()
        }

    except Exception as e:
        logger.error(f"프록시 풀 새로고침 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disable")
async def disable_proxy() -> Dict[str, Any]:
    """
    프록시 사용을 비활성화합니다.

    현재 세션에서만 적용됩니다. 서버 재시작 시 설정값을 따릅니다.
    """
    from app.services.naver_graphql_client import set_proxy_manager

    # NaverGraphQLClient에서 프록시 매니저 제거
    set_proxy_manager(None)

    return {
        "success": True,
        "message": "프록시가 비활성화되었습니다 (현재 세션)",
        "note": "서버 재시작 시 PROXY_ENABLED 설정을 따릅니다"
    }


@router.get("/list")
async def get_proxy_list() -> Dict[str, Any]:
    """
    현재 로드된 프록시 목록을 조회합니다.
    """
    proxy_manager = get_proxy_manager()

    if proxy_manager is None:
        raise HTTPException(
            status_code=400,
            detail="프록시 매니저가 초기화되지 않았습니다"
        )

    return {
        "total": len(proxy_manager.proxy_list),
        "active_pool": proxy_manager.active_pool,
        "blacklisted": list(proxy_manager.blacklist.keys()),
        "all_proxies": proxy_manager.proxy_list
    }
