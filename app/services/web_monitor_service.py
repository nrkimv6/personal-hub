from typing import Dict, Any
from app.models.monitor import MonitorTarget
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.browser_service import BrowserService
from app.services.notification_service import NotificationService
from app.utils.validators import is_content_valid, is_full_reservation, is_page_available
import hashlib
import json
from datetime import datetime

class GenericSiteMonitor(AbstractSiteMonitor):
    """일반적인 웹사이트 모니터링 서비스"""
    
    def __init__(self):
        self.browser_service = BrowserService()
        self.notification_service = NotificationService()
    
    async def check_status(self, target: MonitorTarget) -> Dict[str, Any]:
        """웹 페이지의 상태를 확인합니다."""
        tab = await self.browser_service.get_tab(target.id)
        try:
            new_hash, content, error_type = await self.browser_service.load_page(tab, target.url)
            
            return {
                "hash": new_hash,
                "content": content,
                "error_type": error_type,
                "is_valid": is_content_valid(content) if content else False,
                "is_full": is_full_reservation(content) if content else False,
                "is_available": is_page_available(content) if content else False
            }
        finally:
            await self.browser_service.release_tab(tab)
    
    async def handle_status_change(self, target: MonitorTarget, new_status: Dict[str, Any]) -> None:
        """웹 페이지 상태 변경을 처리합니다."""
        if new_status["error_type"]:
            # 에러 처리
            error_message = f"⚠️ <b>에러 발생</b>\n\n대상: {target.label}\nURL: {target.url}\n에러 유형: {new_status['error_type']}"
            await self.notification_service.send_notification(error_message, force_send=True)
            return
        
        # 상태 변경 알림
        status_message = []
        if new_status["is_valid"]:
            if isinstance(new_status["is_valid"], list):
                available_times = len(new_status["is_valid"])
                status_message.append(f"예약 가능 시간: {available_times}개")
            status_message.append("유효한 콘텐츠")
        else:
            status_message.append("유효하지 않은 콘텐츠")
            
        if new_status["is_full"]:
            status_message.append("예약 마감")
        
        if not new_status["is_available"]:
            status_message.append("페이지 이용 불가")
        
        # 알림 메시지 생성
        message = f"🔄 <b>상태 변경 감지</b>\n\n대상: {target.label}\nURL: {target.url}\n상태: {', '.join(status_message)}"
        await self.notification_service.send_notification(message)
    
    async def get_interval(self, target: MonitorTarget) -> float:
        """웹 페이지 모니터링 간격을 계산합니다."""
        if target.custom_interval and target.interval is not None:
            return target.interval
        
        # 기본 간격 반환
        return 30.0  # 30초
    
    async def validate_target(self, target: MonitorTarget) -> bool:
        """웹 페이지 모니터링 대상의 유효성을 검사합니다."""
        if not target.url or not target.label:
            return False
        
        # URL 형식 검사 등 추가 검증 로직
        return True 