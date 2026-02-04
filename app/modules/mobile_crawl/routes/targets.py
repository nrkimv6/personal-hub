"""
모바일 크롤링 대상 관리 API

크롤링 대상의 생성, 조회, 수정, 삭제를 처리합니다.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import json
import logging

from app.database import get_db
from ..services.target_service import MobileCrawlTargetService
from ..services.item_service import MobileCrawlItemService
from ..services.mobile_server_client import MobileServerClient

logger = logging.getLogger(__name__)

router = APIRouter()


# ============= 스키마 =============

class ParseConfig(BaseModel):
    """파싱 설정"""
    item_container_selector: Optional[str] = Field(None, description="아이템 컨테이너 셀렉터")
    title_selector: Optional[str] = Field(None, description="제목 셀렉터")
    url_selector: Optional[str] = Field(None, description="URL 셀렉터")
    image_selector: Optional[str] = Field(None, description="이미지 셀렉터")
    attribute_selectors: Optional[Dict[str, str]] = Field(None, description="속성 셀렉터 맵")


class CreateTargetRequest(BaseModel):
    """크롤링 대상 생성 요청"""
    name: str = Field(..., description="대상 이름")
    url: str = Field(..., description="대상 URL")
    crawl_type: str = Field("list", description="크롤링 타입 (list, detail)")
    parse_config: Optional[ParseConfig] = Field(None, description="파싱 설정")
    is_active: bool = Field(True, description="활성화 여부")


class UpdateTargetRequest(BaseModel):
    """크롤링 대상 수정 요청"""
    name: Optional[str] = None
    url: Optional[str] = None
    crawl_type: Optional[str] = None
    parse_config: Optional[ParseConfig] = None
    is_active: Optional[bool] = None


class TargetResponse(BaseModel):
    """크롤링 대상 응답"""
    id: int
    name: str
    url: str
    crawl_type: str
    parse_config: str  # JSON 문자열
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TargetStatsResponse(BaseModel):
    """크롤링 대상 통계"""
    total_items: int
    latest_run_id: Optional[int]
    latest_run_at: Optional[str]
    new_items_count: int
    changed_items_count: int


class ExecuteResult(BaseModel):
    """즉시 실행 결과"""
    success: bool
    collected_count: int
    new_count: int
    updated_count: int
    unchanged_count: int
    duration_seconds: float
    error: Optional[str] = None


# ============= API 엔드포인트 =============

@router.post("/targets", response_model=TargetResponse)
def create_target(request: CreateTargetRequest, db: Session = Depends(get_db)):
    """
    크롤링 대상 등록

    새로운 모바일 크롤링 대상을 등록합니다.
    """
    try:
        parse_config_dict = request.parse_config.dict() if request.parse_config else {}

        target = MobileCrawlTargetService.create_target(
            db=db,
            name=request.name,
            url=request.url,
            crawl_type=request.crawl_type,
            parse_config=parse_config_dict,
            is_active=request.is_active
        )

        return TargetResponse(
            id=target.id,
            name=target.name,
            url=target.url,
            crawl_type=target.crawl_type,
            parse_config=target.parse_config,
            is_active=target.is_active,
            created_at=target.created_at.isoformat(),
            updated_at=target.updated_at.isoformat()
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"크롤링 대상 생성 실패: {e}")
        raise HTTPException(status_code=500, detail=f"대상 생성 실패: {str(e)}")


@router.get("/targets", response_model=List[TargetResponse])
def get_targets(
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    크롤링 대상 목록 조회

    등록된 모든 크롤링 대상을 조회합니다.
    """
    targets = MobileCrawlTargetService.get_targets(
        db=db,
        is_active=is_active,
        skip=skip,
        limit=limit
    )

    return [
        TargetResponse(
            id=target.id,
            name=target.name,
            url=target.url,
            crawl_type=target.crawl_type,
            parse_config=target.parse_config,
            is_active=target.is_active,
            created_at=target.created_at.isoformat(),
            updated_at=target.updated_at.isoformat()
        )
        for target in targets
    ]


@router.get("/targets/{target_id}", response_model=TargetResponse)
def get_target(target_id: int, db: Session = Depends(get_db)):
    """
    크롤링 대상 상세 조회

    특정 크롤링 대상의 상세 정보를 조회합니다.
    """
    target = MobileCrawlTargetService.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다")

    return TargetResponse(
        id=target.id,
        name=target.name,
        url=target.url,
        crawl_type=target.crawl_type,
        parse_config=target.parse_config,
        is_active=target.is_active,
        created_at=target.created_at.isoformat(),
        updated_at=target.updated_at.isoformat()
    )


@router.put("/targets/{target_id}", response_model=TargetResponse)
def update_target(
    target_id: int,
    request: UpdateTargetRequest,
    db: Session = Depends(get_db)
):
    """
    크롤링 대상 수정

    크롤링 대상의 정보를 수정합니다.
    """
    try:
        parse_config_dict = None
        if request.parse_config is not None:
            parse_config_dict = request.parse_config.dict()

        target = MobileCrawlTargetService.update_target(
            db=db,
            target_id=target_id,
            name=request.name,
            url=request.url,
            crawl_type=request.crawl_type,
            parse_config=parse_config_dict,
            is_active=request.is_active
        )

        if not target:
            raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다")

        return TargetResponse(
            id=target.id,
            name=target.name,
            url=target.url,
            crawl_type=target.crawl_type,
            parse_config=target.parse_config,
            is_active=target.is_active,
            created_at=target.created_at.isoformat(),
            updated_at=target.updated_at.isoformat()
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"크롤링 대상 수정 실패: {e}")
        raise HTTPException(status_code=500, detail=f"대상 수정 실패: {str(e)}")


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    """
    크롤링 대상 삭제

    크롤링 대상을 삭제합니다. 관련된 아이템도 함께 삭제됩니다.
    """
    success = MobileCrawlTargetService.delete_target(db, target_id)
    if not success:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다")

    return {"success": True}


@router.get("/targets/{target_id}/stats", response_model=TargetStatsResponse)
def get_target_stats(target_id: int, db: Session = Depends(get_db)):
    """
    크롤링 대상 통계

    대상의 수집 통계를 조회합니다.
    """
    stats = MobileCrawlTargetService.get_target_stats(db, target_id)
    if not stats:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다")

    return TargetStatsResponse(**stats)


@router.post("/targets/{target_id}/execute", response_model=ExecuteResult)
async def execute_target(target_id: int, db: Session = Depends(get_db)):
    """
    즉시 크롤링 실행

    크롤링 대상을 즉시 실행합니다.
    모바일 서버를 호출하여 HTML을 수집하고, 아이템을 파싱하여 저장합니다.

    TODO: Phase 5-1, 5-2 완료 후 실제 크롤링 로직 연결
    """
    import time

    target = MobileCrawlTargetService.get_target(db, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="대상을 찾을 수 없습니다")

    start_time = time.time()

    try:
        # TODO: Phase 5-1, 5-2에서 모바일 서버의 구조화 크롤링 API 호출
        # mobile_client = MobileServerClient()
        # result = await mobile_client.crawl(
        #     url=target.url,
        #     parse_config=json.loads(target.parse_config)
        # )
        #
        # # 아이템 저장
        # stats = MobileCrawlItemService.save_items(
        #     db=db,
        #     target_id=target.id,
        #     run_id=None,  # 수동 실행은 run_id 없음
        #     items=result["items"]
        # )

        # 임시: 빈 결과 반환
        stats = {"new": 0, "updated": 0, "unchanged": 0}
        collected_count = 0

        duration = time.time() - start_time

        return ExecuteResult(
            success=True,
            collected_count=collected_count,
            new_count=stats["new"],
            updated_count=stats["updated"],
            unchanged_count=stats["unchanged"],
            duration_seconds=duration,
            error=None
        )

    except Exception as e:
        logger.error(f"즉시 크롤링 실행 실패: {e}")
        duration = time.time() - start_time

        return ExecuteResult(
            success=False,
            collected_count=0,
            new_count=0,
            updated_count=0,
            unchanged_count=0,
            duration_seconds=duration,
            error=str(e)
        )
