import aiohttp
from plyer import notification
from datetime import datetime, timedelta
from collections import deque
import hashlib
import re
from typing import Optional, Dict, Any, List
import json
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from app.core.config import settings, logger
from app.modules.naver_booking.utils.validators import is_naver_content_valid, is_naver_full_reservation, is_naver_page_available
from app.modules.naver_booking.utils.parsers import parse_time_and_stock, parse_naver_page_info
from app.utils.parsers import extract_date_from_url
from app.core.database import SessionLocal, get_db

class NotificationService:
    def __init__(self):
        self.db = next(get_db())
        self._load_settings()
        self.telegram_bot_token = settings.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = settings.TELEGRAM_CHAT_ID
        self.enable_desktop = settings.ENABLE_DESKTOP_NOTIFICATION
        
        # 중복 메시지 필터링을 위한 변수들
        self.recent_messages = deque(maxlen=settings.RECENT_MESSAGES_MAX)
        self.message_timestamps = {}  # 메시지 해시: 타임스탬프
        
        # URL 상태 캐시
        self.url_status_cache = {}  # url: {"status": str, "last_update": datetime}
        
        # 시간별 알림 로그
        self.time_alert_log = {}  # url: {time_key: last_alert_time}
        
    def _load_settings(self):
        """알림 설정을 로드합니다."""
        try:
            result = self.db.execute(text("""
                SELECT enable_telegram, enable_desktop, notify_states
                FROM notification_settings WHERE id = 1
            """)).fetchone()

            if not result:
                # 기본 설정 생성
                self.db.execute(text("""
                    INSERT INTO notification_settings (id, enable_telegram, enable_desktop, notify_states)
                    VALUES (1, 1, 1, '[]')
                """))
                self.db.commit()
                self.enable_telegram = True
                self.enable_desktop = True
                self.notify_states = []
            else:
                self.enable_telegram = bool(result[0])
                self.enable_desktop = bool(result[1])
                self.notify_states = json.loads(result[2]) if result[2] else []
        except Exception as e:
            logger.warning(f"알림 설정 로드 실패: {e}, 기본값 사용")
            self.enable_telegram = True
            self.enable_desktop = True
            self.notify_states = []

    def should_notify(self, state: str) -> bool:
        """특정 상태에 대해 알림을 보내야 하는지 확인합니다.

        Args:
            state: 알림 상태 (예: "startup", "shutdown", "available", "booking_success", "booking_failed", "error")

        Returns:
            bool: 알림을 보내야 하면 True
        """
        self._load_settings()
        return self.enable_telegram and state in self.notify_states
        
    def _hash_message(self, message: str) -> str:
        """메시지의 해시값을 계산합니다."""
        return hashlib.md5(message.encode('utf-8')).hexdigest()
        
    def _is_duplicate_message(self, message: str, url: str = None, status: str = None, time_info: list = None) -> bool:
        """메시지가 중복인지 확인합니다.
        
        Args:
            message: 알림 메시지
            url: 대상 URL (선택적)
            status: 현재 상태 (선택적)
            time_info: 시간 정보 목록 (선택적)
            
        Returns:
            bool: 중복 메시지 여부
        """
        if not settings.MESSAGE_DEDUPLICATION:
            return False
            
        # 오래된 메시지 제거
        current_time = datetime.now()
        expiry_delta = timedelta(seconds=settings.MESSAGE_EXPIRY_SECONDS)
        
        # 만료된 메시지 제거
        expired_hashes = []
        for msg_hash, timestamp in self.message_timestamps.items():
            if current_time - timestamp > expiry_delta:
                expired_hashes.append(msg_hash)
                
        for msg_hash in expired_hashes:
            if msg_hash in self.message_timestamps:
                del self.message_timestamps[msg_hash]
        
        # 기본 해시 계산
        msg_hash = self._hash_message(message)
        
        # 시간 정보와 URL 상태를 결합한 고급 필터링
        # URL과 상태 정보가 제공된 경우
        if url and status and time_info:
            # URL 상태 확인
            url_info = self._get_url_status(url)
            last_update_time = url_info.get("last_update")
            
            # 마지막 상태 업데이트 시간이 10분 이내인지 확인
            if last_update_time and current_time - last_update_time < timedelta(minutes=10):
                # 상태가 동일하고 동일한 시간 정보가 있는 경우
                if url_info.get("status") == status:
                    # 시간 정보 중복 확인
                    for time_str in time_info:
                        if self._is_time_recently_alerted(url, time_str):
                            print(f"시간 정보 중복 감지: {url} - {time_str}")
                            return True
                            
            # 특별한 상태 변화의 경우 항상 알림 (예: 매진→예약가능)
            if status == "예약가능" and url_info.get("status") == "매진":
                print(f"중요 상태 변화 감지! {url_info.get('status')} → {status}")
                # 중요 변경은 필터링하지 않음
                pass
        
        # 일반 해시 기반 중복 확인
        if msg_hash in self.message_timestamps:
            time_diff = (current_time - self.message_timestamps[msg_hash]).total_seconds()
            print(f"중복 메시지 감지됨: {message[:30]}... ({int(time_diff)}초 전)")
            return True
            
        # 새 메시지 추가
        self.message_timestamps[msg_hash] = current_time
        self.recent_messages.append(message)
        return False
        
    def _get_time_key(self, time_str: str) -> str:
        """시간 문자열에서 고유 키를 생성합니다."""
        # 시간 정보만 추출 (공백, 특수문자 제거)
        return re.sub(r'[^0-9:]', '', time_str)
        
    def _is_time_recently_alerted(self, url: str, time_str: str) -> bool:
        """특정 시간에 대한 알림이 최근에 발송되었는지 확인합니다."""
        if not url in self.time_alert_log:
            self.time_alert_log[url] = {}
            
        time_key = self._get_time_key(time_str)
        if not time_key:
            return False
            
        current_time = datetime.now()
        
        # 해당 시간에 대한 마지막 알림 시간 확인
        if time_key in self.time_alert_log[url]:
            last_alert = self.time_alert_log[url][time_key]
            # 10분 이내에 알림이 발송된 경우
            if current_time - last_alert < timedelta(minutes=10):
                return True
                
        # 알림 시간 갱신
        self.time_alert_log[url][time_key] = current_time
        return False

    def _get_url_status(self, url: str) -> Dict[str, Any]:
        """URL의 현재 상태 정보를 반환합니다."""
        if url not in self.url_status_cache:
            self.url_status_cache[url] = {
                "status": "미확인",
                "last_update": datetime.now(),
                "change_count": 0
            }
        return self.url_status_cache[url]

    def _update_url_status(self, url: str, new_status: str) -> str:
        """URL 상태를 업데이트하고 변경 유형을 반환합니다."""
        current_info = self._get_url_status(url)
        old_status = current_info["status"]
        
        # 상태가 변경된 경우
        if old_status != new_status:
            current_info["status"] = new_status
            current_info["last_update"] = datetime.now()
            current_info["change_count"] += 1
            
            # 변경 유형 결정
            if old_status == "미확인":
                change_type = "초기화"
            elif old_status == "매진" and new_status == "예약가능":
                change_type = "매진→예약가능"
            elif old_status == "예약가능" and new_status == "매진":
                change_type = "예약가능→매진"
            elif old_status == "에러" and new_status != "에러":
                change_type = "에러해결"
            elif old_status != "에러" and new_status == "에러":
                change_type = "에러발생"
            else:
                change_type = "상태변경"
                
            return change_type
        
        return "변화없음"

    async def send_notification(self, target: Dict[str, Any], status: Dict[str, Any]) -> None:
        """
        모니터링 상태 변화에 대한 알림을 발송합니다.
        """
        try:
            # 텔레그램 알림 발송
            await self._send_telegram_notification(target, status)
            
            # 상태 변화 로깅
            logger.info(f"Notification sent for target {target.get('id')}: {status}")
            
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
            raise

    async def send_notification_message(self, message: str, send_desktop: bool = False, force_send: bool = False) -> None:
        """
        단순 문자열 메시지를 알림으로 발송합니다.
        
        Args:
            message: 발송할 메시지
            send_desktop: 데스크톱 알림 발송 여부
            force_send: 중복 메시지 검사를 건너뛰고 강제로 발송할지 여부
        """
        try:
            # 텔레그램 알림 발송
            await self._send_telegram(message)
            
            # 데스크톱 알림 발송 (요청된 경우)
            if send_desktop:
                await self._send_desktop(message)
            
            # 로깅
            logger.info(f"Notification message sent: {message[:100]}...")
            
        except Exception as e:
            logger.error(f"Error sending notification message: {str(e)}")
            raise

    async def _send_telegram_notification(self, target: Dict[str, Any], status: Dict[str, Any]) -> None:
        """
        텔레그램으로 알림을 발송합니다.
        """
        try:
            message = f"🔔 {target.get('label')}\n"
            message += f"상태: {status.get('status', 'unknown')}\n"
            message += f"URL: {target.get('url')}"

            await self._send_telegram(message)
        except Exception as e:
            logger.error(f"텔레그램 알림 전송 중 오류 발생: {str(e)}")
            raise

    async def _send_telegram(self, message: str):
        """텔레그램으로 알림을 전송합니다."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("텔레그램 설정이 없어 알림을 전송할 수 없습니다.")
            return
            
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"텔레그램 알림 전송 실패: {str(e)}")
            return False

    async def _send_desktop(self, message: str):
        """데스크톱 알림을 전송합니다."""
        if not self.enable_desktop:
            return
            
        # 중복 메시지 확인
        combined_message = f"{message}"
        if self._is_duplicate_message(combined_message):
            print("중복 메시지로 데스크톱 알림 발송 건너뜀")
            return

        try:
            # Windows 알림 시스템은 메시지 길이에 256자 제한이 있으므로 메시지를 잘라냅니다
            if len(message) > 256:
                message = message[:253] + "..."
                
            notification.notify(
                title="알림",
                message=message,
                timeout=10
            )
            return True
        except Exception as e:
            logger.error(f"데스크톱 알림 전송 실패: {str(e)}")
            return False

    def _get_notification_emoji(self, status: str, change_type: str) -> str:
        """상태와 변경 유형에 따른 이모지를 반환합니다."""
        if change_type == "매진→예약가능":
            return "✅"  # 예약 가능해짐
        elif change_type == "예약가능→매진":
            return "❌"  # 매진됨
        elif change_type == "에러발생":
            return "⚠️"  # 에러 발생
        elif change_type == "에러해결":
            return "🔄"  # 에러 해결
        elif status == "예약가능":
            return "🔔"  # 일반 변경 (예약 가능)
        else:
            return "ℹ️"  # 일반 정보
            
    def _get_notification_title(self, status: str, change_type: str) -> str:
        """상태와 변경 유형에 따른 알림 제목을 반환합니다."""
        emoji = self._get_notification_emoji(status, change_type)
        
        if change_type == "매진→예약가능":
            return f"{emoji} 예약 가능해짐"
        elif change_type == "예약가능→매진":
            return f"{emoji} 매진됨"
        elif change_type == "에러발생":
            return f"{emoji} 에러 발생"
        elif change_type == "에러해결":
            return f"{emoji} 에러 해결됨"
        elif status == "예약가능":
            return f"{emoji} 변경 감지 (예약가능)"
        else:
            return f"{emoji} 변경 감지"
            
    def _format_time_info(self, times: List[str]) -> str:
        """시간 정보를 보기 좋게 포맷팅합니다."""
        if not times:
            return ""
            
        # 시간 정렬
        try:
            # '오전 10:00' 형식의 시간 문자열 정렬
            sorted_times = sorted(times, key=lambda x: (
                0 if "오전" in x else 1,  # 오전이 먼저 오도록
                int(re.search(r'(\d+):', x).group(1)),  # 시간으로 정렬
                int(re.search(r':(\d+)', x).group(1))   # 분으로 정렬
            ))
            return ", ".join(sorted_times)
        except:
            # 정렬에 실패하면 원래 순서 유지
            return ", ".join(times)
            
    def _format_stock_info(self, stocks: List[str]) -> str:
        """매수 정보를 보기 좋게 포맷팅합니다."""
        if not stocks:
            return ""
            
        # 매수 정보 분석 및 정렬
        try:
            # 매수 정보 정렬
            def extract_time_and_stock(s):
                time_match = re.search(r'(오전|오후)\s+\d+:\d+', s)
                time_str = time_match.group(0) if time_match else ""
                
                stock_match = re.search(r':\s*(\d+)매', s)
                stock_num = int(stock_match.group(1)) if stock_match else 0
                
                return (0 if "오전" in time_str else 1, 
                       int(re.search(r'(\d+):', time_str).group(1)) if time_str else 0,
                       int(re.search(r':(\d+)', time_str).group(1)) if time_str else 0,
                       -stock_num)  # 매수가 많은 것이 먼저 오도록 음수 처리
                       
            sorted_stocks = sorted(stocks, key=extract_time_and_stock)
            
            # 매수 정보 강조 (3매 이상은 굵게 표시)
            formatted_stocks = []
            for stock in sorted_stocks:
                stock_match = re.search(r':\s*(\d+)매', stock)
                if stock_match and int(stock_match.group(1)) >= 3:
                    # 숫자만 굵게 처리
                    formatted = re.sub(r'(\d+매)', r'<b>\1</b>', stock)
                    formatted_stocks.append(formatted)
                else:
                    formatted_stocks.append(stock)
                    
            return "\n".join(formatted_stocks)
        except:
            # 정렬에 실패하면 원래 순서로 리턴
            return "\n".join(stocks)

    async def notify_change(self, target_id: int, url: str, label: str, content: str, last_check_time=None, validity_info=None, 
                           send_telegram: bool = None, send_desktop: bool = None):
        """변경 사항을 알립니다.
        
        Args:
            target_id: 모니터링 대상 ID
            url: 모니터링 URL
            label: 모니터링 라벨
            content: 페이지 콘텐츠
            last_check_time: 마지막 확인 시간
            validity_info: 유효성 검사 결과 정보 (선택적)
            send_telegram: 텔레그램 알림 발송 여부 (None인 경우 설정값 사용)
            send_desktop: 데스크톱 알림 발송 여부 (None인 경우 설정값 사용)
        """
        try:
            # 알림 설정 로드
            self._load_settings()
            
            # 알림 상태 확인
            if validity_info:
                current_status = "available" if validity_info.get("is_valid") else "error"
                if current_status not in self.notify_states:
                    logger.debug(f"현재 상태 {current_status}가 알림 설정에 포함되지 않아 알림을 보내지 않습니다.")
                    return
            
            # 알림 메시지 생성
            message = f"🔔 <b>{label}</b>\n\n"
            message += f"URL: {url}\n"
            
            if validity_info:
                if validity_info.get("is_valid"):
                    message += "상태: 예약 가능\n"
                elif validity_info.get("is_full"):
                    message += "상태: 매진\n"
                else:
                    message += "상태: 에러\n"
            
            # 텔레그램 알림 전송
            if send_telegram is None:
                send_telegram = self.enable_telegram
                
            if send_telegram:
                await self.send_telegram(message)
            
            # 데스크톱 알림 전송
            if send_desktop is None:
                send_desktop = self.enable_desktop
                
            if send_desktop:
                await self._send_desktop(message)
                
        except Exception as e:
            logger.error(f"알림 전송 중 오류 발생: {str(e)}")

    async def send_telegram(self, message: str, force_send: bool = False):
        """텔레그램으로 알림을 보냅니다."""
        if not self.enable_telegram and not force_send:
            return
            
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("텔레그램 봇 토큰이나 채팅 ID가 설정되지 않았습니다.")
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                data = {
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
                async with session.post(url, json=data) as response:
                    if response.status != 200:
                        logger.error(f"텔레그램 알림 전송 실패: {await response.text()}")
        except Exception as e:
            logger.error(f"텔레그램 알림 전송 중 오류 발생: {str(e)}") 