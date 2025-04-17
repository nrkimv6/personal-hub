from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.services.browser_service import BrowserService
from app.config import logger

# 전역 BrowserService 인스턴스
_browser_service = None

async def get_browser_service() -> BrowserService:
    """초기화된 BrowserService 인스턴스를 반환합니다."""
    global _browser_service
    logger.info("get_browser_service 호출됨")
    if _browser_service is None:
        logger.info("BrowserService 새로 생성")
        _browser_service = BrowserService()
        logger.info("BrowserService.initialize() 호출 시작")
        await _browser_service.initialize()
        logger.info("BrowserService.initialize() 호출 완료")
    else:
        logger.info("기존 BrowserService 인스턴스 재사용")
    return _browser_service

def get_db_session() -> Session:
    return SessionLocal()

# 불필요한 BrowserServiceDep 정의를 제거 