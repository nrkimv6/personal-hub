"""
EntitySource API 라우트 - 이벤트/팝업 다중 출처 관리

GET 엔드포인트는 공개, CUD 엔드포인트는 관리자 인증 필요
"""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.entity_source_service import entity_source_service
from app.schemas.entity_source import (
    EntitySourceCreate,
    EntitySourceUpdate,
    EntitySourceResponse,
    EntitySourceList,
)
from app.core.auth import require_admin, UserInfo

router = APIRouter(prefix="/api/v1", tags=["entity-sources"])


@router.get(
    "/{entity_type}/{entity_id}/sources",
    response_model=EntitySourceList,
)
def get_sources(
    entity_type: Literal["events", "popups"] = Path(..., description="엔티티 타입"),
    entity_id: int = Path(..., description="엔티티 ID"),
    db: Session = Depends(get_db),
):
    """
    엔티티의 출처 목록을 조회합니다.

    - events/{id}/sources: 이벤트의 출처 목록
    - popups/{id}/sources: 팝업의 출처 목록
    """
    # URL path에서 's' 제거 (events -> event, popups -> popup)
    normalized_type = entity_type.rstrip("s")
    return entity_source_service.get_sources(db, normalized_type, entity_id)


@router.post(
    "/{entity_type}/{entity_id}/sources",
    response_model=EntitySourceResponse,
    status_code=201,
)
def add_source(
    entity_type: Literal["events", "popups"] = Path(..., description="엔티티 타입"),
    entity_id: int = Path(..., description="엔티티 ID"),
    data: EntitySourceCreate = ...,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    엔티티에 새 출처를 추가합니다. (관리자 전용)

    - 첫 번째 출처는 자동으로 대표(primary) 출처로 설정됨
    - 동일 출처가 이미 존재하면 기존 출처 반환
    """
    normalized_type = entity_type.rstrip("s")
    result = entity_source_service.add_source(db, normalized_type, entity_id, data)
    if not result:
        raise HTTPException(status_code=404, detail=f"{entity_type[:-1].title()} not found")
    return result


@router.delete(
    "/{entity_type}/{entity_id}/sources/{source_id}",
    status_code=204,
)
def remove_source(
    entity_type: Literal["events", "popups"] = Path(..., description="엔티티 타입"),
    entity_id: int = Path(..., description="엔티티 ID"),
    source_id: int = Path(..., description="출처 ID"),
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    엔티티에서 출처를 제거합니다. (관리자 전용)

    - 대표 출처가 삭제되면 다음 우선순위 출처가 대표로 설정됨
    """
    normalized_type = entity_type.rstrip("s")
    success = entity_source_service.remove_source(db, normalized_type, entity_id, source_id)
    if not success:
        raise HTTPException(status_code=404, detail="Source not found")
    return None


@router.put(
    "/{entity_type}/{entity_id}/sources/{source_id}/primary",
    response_model=EntitySourceResponse,
)
def set_primary_source(
    entity_type: Literal["events", "popups"] = Path(..., description="엔티티 타입"),
    entity_id: int = Path(..., description="엔티티 ID"),
    source_id: int = Path(..., description="출처 ID"),
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    대표 출처를 변경합니다. (관리자 전용)

    - 기존 대표 출처는 해제됨
    - 지정된 출처가 새 대표 출처로 설정됨
    """
    normalized_type = entity_type.rstrip("s")
    result = entity_source_service.set_primary(db, normalized_type, entity_id, source_id)
    if not result:
        raise HTTPException(status_code=404, detail="Source not found")
    return result


@router.patch(
    "/{entity_type}/{entity_id}/sources/{source_id}",
    response_model=EntitySourceResponse,
)
def update_source(
    entity_type: Literal["events", "popups"] = Path(..., description="엔티티 타입"),
    entity_id: int = Path(..., description="엔티티 ID"),
    source_id: int = Path(..., description="출처 ID"),
    data: EntitySourceUpdate = ...,
    db: Session = Depends(get_db),
    admin: UserInfo = Depends(require_admin),
):
    """
    출처 정보를 수정합니다. (관리자 전용)

    - 우선순위, contributed_fields 수정 가능
    """
    result = entity_source_service.update_source(db, source_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Source not found")
    return result
