"""Dev Runner Settings API — GET/PUT 엔드포인트"""

from fastapi import APIRouter, HTTPException

from app.config import logger
from app.modules.dev_runner.schemas import DevRunnerSettingsResponse, DevRunnerSettingsUpdateRequest
from app.modules.dev_runner.services.settings_service import settings_service

router = APIRouter(tags=["dev-runner-settings"])


@router.get("", response_model=DevRunnerSettingsResponse)
async def get_settings():
    """현재 dev-runner 설정 반환"""
    settings = settings_service.get()
    return DevRunnerSettingsResponse(
        max_concurrent_runners=settings.max_concurrent_runners,
        default_engine=settings.default_engine,
        default_fix_engine=settings.default_fix_engine,
        updated_at=settings.updated_at,
    )


@router.put("", response_model=DevRunnerSettingsResponse)
async def update_settings(body: DevRunnerSettingsUpdateRequest):
    """dev-runner 설정 업데이트"""
    try:
        payload = body.model_dump(exclude_none=True)
        if not payload:
            raise HTTPException(status_code=422, detail="최소 1개 필드를 전달해야 합니다.")
        settings = settings_service.update(payload)
        return DevRunnerSettingsResponse(
            max_concurrent_runners=settings.max_concurrent_runners,
            default_engine=settings.default_engine,
            default_fix_engine=settings.default_fix_engine,
            updated_at=settings.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
