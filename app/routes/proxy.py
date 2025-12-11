"""
프록시 상태 API 라우트
작성일: 2025-12-11

프록시 매니저 상태 조회 및 관리 API를 제공합니다.
- 파일 기반 ProxyManager: /status, /initialize, /refresh, /disable, /list (legacy)
- DB 기반 ProxyDBService: /db/stats, /db/list, /db/{id}, /db/runs, /db/import
"""

from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.core.config import settings, logger
from app.database import get_db
from app.services.proxy_manager import get_proxy_manager, init_proxy_manager, ProxyManager
from app.services.proxy_db_service import ProxyDBService, get_proxy_db_service
from app.schemas.proxy import (
    ProxyStatsResponse,
    ProxyListParams,
    ProxyListResponse,
    ProxyResponse,
    ProxyDetailResponse,
    ProxyUpdate,
    ProxyCollectionRunResponse,
    ProxyImportResult,
    ProxyCheckHistoryResponse,
)

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
    현재 로드된 프록시 목록을 조회합니다. (파일 기반, legacy)
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


# ============== DB 기반 API ==============

@router.get("/db/stats", response_model=ProxyStatsResponse)
async def get_proxy_db_stats(db: Session = Depends(get_db)) -> ProxyStatsResponse:
    """
    프록시 전체 통계를 조회합니다. (DB 기반)

    Returns:
        - total: 전체 프록시 수
        - active: 활성 프록시 수
        - pending: 대기 중 프록시 수
        - inactive: 비활성 프록시 수
        - blacklisted: 블랙리스트 프록시 수
        - avg_response_time: 평균 응답 시간
        - overall_success_rate: 전체 성공률
        - by_protocol: 프로토콜별 분포
        - by_country: 국가별 분포
        - today_checks: 오늘 검증 횟수
        - today_success_rate: 오늘 성공률
    """
    service = get_proxy_db_service(db)
    return service.get_stats()


@router.get("/db/list", response_model=ProxyListResponse)
async def get_proxy_db_list(
    status: Optional[str] = Query(None, description="상태 필터 (pending/active/inactive/blacklisted)"),
    protocol: Optional[str] = Query(None, description="프로토콜 필터 (http/https/socks5)"),
    country: Optional[str] = Query(None, description="국가 필터"),
    search: Optional[str] = Query(None, description="검색어 (URL, IP)"),
    sort_by: str = Query("priority_score", description="정렬 기준"),
    sort_order: str = Query("desc", description="정렬 방향 (asc/desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=100, description="페이지당 항목 수"),
    db: Session = Depends(get_db),
) -> ProxyListResponse:
    """
    프록시 목록을 조회합니다. (DB 기반, 필터/정렬/페이징)
    """
    params = ProxyListParams(
        status=status,
        protocol=protocol,
        country=country,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    service = get_proxy_db_service(db)
    return service.get_list(params)


@router.get("/db/top", response_model=List[ProxyResponse])
async def get_top_proxies(
    limit: int = Query(10, ge=1, le=100, description="조회할 프록시 수"),
    status: str = Query("active", description="상태 필터"),
    db: Session = Depends(get_db),
) -> List[ProxyResponse]:
    """
    상위 프록시 목록을 조회합니다. (우선순위순)
    """
    service = get_proxy_db_service(db)
    proxies = service.get_top_proxies(limit=limit, status=status)
    return [ProxyResponse.model_validate(p) for p in proxies]


@router.get("/db/{proxy_id}", response_model=ProxyDetailResponse)
async def get_proxy_detail(
    proxy_id: int,
    history_limit: int = Query(50, ge=1, le=200, description="검증 이력 조회 수"),
    db: Session = Depends(get_db),
) -> ProxyDetailResponse:
    """
    프록시 상세 정보를 조회합니다. (검증 이력 포함)
    """
    service = get_proxy_db_service(db)
    detail = service.get_detail(proxy_id, history_limit=history_limit)

    if not detail:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")

    return detail


@router.get("/db/{proxy_id}/history", response_model=List[ProxyCheckHistoryResponse])
async def get_proxy_history(
    proxy_id: int,
    limit: int = Query(50, ge=1, le=200, description="조회할 이력 수"),
    offset: int = Query(0, ge=0, description="오프셋"),
    db: Session = Depends(get_db),
) -> List[ProxyCheckHistoryResponse]:
    """
    프록시 검증 이력을 조회합니다.
    """
    service = get_proxy_db_service(db)

    # 프록시 존재 확인
    proxy = service.get_by_id(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")

    history = service.get_check_history(proxy_id, limit=limit, offset=offset)
    return [ProxyCheckHistoryResponse.model_validate(h) for h in history]


@router.patch("/db/{proxy_id}/status")
async def update_proxy_status(
    proxy_id: int,
    status: str = Query(..., description="변경할 상태 (pending/active/inactive/blacklisted)"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    프록시 상태를 변경합니다.
    """
    valid_statuses = ["pending", "active", "inactive", "blacklisted"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 상태입니다. 가능한 값: {valid_statuses}"
        )

    service = get_proxy_db_service(db)
    proxy = service.update_status(proxy_id, status)

    if not proxy:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")

    return {
        "success": True,
        "message": f"프록시 상태가 '{status}'로 변경되었습니다",
        "proxy": ProxyResponse.model_validate(proxy),
    }


@router.delete("/db/{proxy_id}")
async def delete_proxy(
    proxy_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    프록시를 삭제합니다.
    """
    service = get_proxy_db_service(db)
    success = service.delete(proxy_id)

    if not success:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")

    return {
        "success": True,
        "message": "프록시가 삭제되었습니다",
    }


@router.get("/db/runs", response_model=List[ProxyCollectionRunResponse])
async def get_collection_runs(
    limit: int = Query(20, ge=1, le=100, description="조회할 이력 수"),
    status: Optional[str] = Query(None, description="상태 필터"),
    db: Session = Depends(get_db),
) -> List[ProxyCollectionRunResponse]:
    """
    프록시 수집 실행 이력을 조회합니다.
    """
    service = get_proxy_db_service(db)
    runs = service.get_collection_runs(limit=limit, status=status)
    return [ProxyCollectionRunResponse.model_validate(r) for r in runs]


@router.post("/db/import", response_model=ProxyImportResult)
async def import_proxies_from_file(
    file_path: Optional[str] = Query(None, description="프록시 파일 경로 (기본: shared/proxies/proxy_list.txt)"),
    source: str = Query("file_import", description="소스 이름"),
    db: Session = Depends(get_db),
) -> ProxyImportResult:
    """
    프록시 파일에서 DB로 임포트합니다.

    파일 형식:
    - 한 줄에 하나의 프록시 URL
    - # 으로 시작하는 줄은 주석
    - 예: http://1.2.3.4:8080  # comment
    """
    if file_path:
        path = Path(file_path)
    else:
        # 기본 경로: shared/proxies/proxy_list.txt
        path = Path(__file__).resolve().parents[3] / "shared" / "proxies" / "proxy_list.txt"

    service = get_proxy_db_service(db)
    result = service.import_from_file(path, source=source)

    logger.info(
        f"프록시 임포트 완료: 파싱 {result.total_parsed}, "
        f"신규 {result.new_count}, 업데이트 {result.updated_count}, "
        f"스킵 {result.skipped_count}"
    )

    return result


@router.post("/db/cleanup")
async def cleanup_proxy_data(
    history_days: int = Query(90, ge=1, description="검증 이력 보관 일수"),
    stale_days: int = Query(7, ge=1, description="비활성화 기준 일수"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    오래된 프록시 데이터를 정리합니다.

    - history_days: 이 일수보다 오래된 검증 이력 삭제
    - stale_days: 이 일수 동안 연속 실패한 프록시 비활성화
    """
    service = get_proxy_db_service(db)

    deleted_history = service.cleanup_old_history(days=history_days)
    deactivated_proxies = service.deactivate_stale_proxies(days=stale_days)

    return {
        "success": True,
        "deleted_history_count": deleted_history,
        "deactivated_proxy_count": deactivated_proxies,
    }
