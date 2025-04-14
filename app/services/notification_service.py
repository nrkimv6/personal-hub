import aiohttp
from plyer import notification
from datetime import datetime, timedelta
from collections import deque
import hashlib
import re
from typing import Optional, Dict, Any

from app.config import settings
from app.utils.validators import is_content_valid, is_full_reservation, is_page_available
from app.utils.parsers import parse_time_and_stock, parse_page_info, extract_date_from_url

class NotificationService:
    def __init__(self):
        self.telegram_bot_token = settings.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = settings.TELEGRAM_CHAT_ID
        self.enable_desktop = settings.ENABLE_DESKTOP_NOTIFICATION
        
        # 중복 메시지 필터링을 위한 변수들
        self.recent_messages = deque(maxlen=settings.RECENT_MESSAGES_MAX)
        self.message_timestamps = {}  # 메시지 해시: 타임스탬프
        
        # URL 상태 캐시
        self.url_status_cache = {}  # url: {"status": str, "last_update": datetime}
        
    def _hash_message(self, message: str) -> str:
        """메시지의 해시값을 계산합니다."""
        return hashlib.md5(message.encode('utf-8')).hexdigest()
        
    def _is_duplicate_message(self, message: str) -> bool:
        """메시지가 중복인지 확인합니다."""
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
                
        # 중복 확인
        msg_hash = self._hash_message(message)
        if msg_hash in self.message_timestamps:
            print(f"중복 메시지 감지됨: {message[:30]}...")
            return True
            
        # 새 메시지 추가
        self.message_timestamps[msg_hash] = current_time
        self.recent_messages.append(message)
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

    async def send_telegram(self, message: str) -> bool:
        """텔레그램으로 알림을 보냅니다."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False
            
        # 중복 메시지 확인
        if self._is_duplicate_message(message):
            print("중복 메시지로 텔레그램 알림 발송 건너뜀")
            return False

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
            print(f"텔레그램 알림 발송 실패: {str(e)}")
            return False

    def send_desktop(self, title: str, message: str) -> bool:
        """데스크톱 알림을 보냅니다."""
        if not self.enable_desktop:
            return False
            
        # 중복 메시지 확인
        combined_message = f"{title}:{message}"
        if self._is_duplicate_message(combined_message):
            print("중복 메시지로 데스크톱 알림 발송 건너뜀")
            return False

        try:
            # Windows 알림 시스템은 메시지 길이에 256자 제한이 있으므로 메시지를 잘라냅니다
            if len(message) > 256:
                message = message[:253] + "..."
                
            notification.notify(
                title=title,
                message=message,
                timeout=10
            )
            return True
        except Exception as e:
            print(f"데스크톱 알림 발송 실패: {str(e)}")
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

    async def notify_change(self, target_id: int, url: str, label: str, content: str, last_check_time=None):
        """변경 사항을 알립니다."""
        # 현재 시간과 경과 시간 계산
        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 마지막 확인 시간부터 현재까지의 경과 시간 계산
        elapsed_time_str = "확인 불가"
        if last_check_time:
            elapsed_seconds = (current_time - last_check_time).total_seconds()
            elapsed_minutes = int(elapsed_seconds // 60)
            elapsed_seconds = int(elapsed_seconds % 60)
            elapsed_time_str = f"{elapsed_minutes}분 {elapsed_seconds}초"
        
        # 콘텐츠 유효성 검사 및 정보 파싱
        page_info = parse_page_info(content)
        
        # 콘텐츠 상태 결정
        if page_info["available"] and page_info["times"]:
            status = "예약가능"
        elif is_full_reservation(content):
            status = "매진"
        elif not is_page_available(content):
            status = "에러"
        else:
            status = "변경"
            
        # URL 상태 업데이트
        change_type = self._update_url_status(url, status)
        
        # 알림 제목 결정
        notification_title = self._get_notification_title(status, change_type)
        
        # 텔레그램 메시지 구성
        telegram_message = (
            f"{notification_title}\n\n"
            f"대상: {label}\n"
        )
        
        # 제목 정보 추가
        if page_info["title"]:
            telegram_message += f"제목: {page_info['title']}\n"
        
        # 기본 정보 추가
        telegram_message += (
            f"URL: {url}\n"
            f"시간: {timestamp}\n"
            f"마지막 확인 후 경과: {elapsed_time_str}\n"
            f"ID: {target_id}"
        )
        
        # 날짜 정보 추가
        target_date = extract_date_from_url(url)
        if target_date:
            telegram_message += f"\n날짜: {target_date}"
        
        # 시간 정보 추가
        if page_info["times"]:
            telegram_message += f"\n\n<b>예약 가능 시간:</b> {', '.join(page_info['times'])}"
        
        # 매수 정보 추가
        if page_info["stocks"]:
            telegram_message += f"\n<b>매수 정보:</b> {', '.join(page_info['stocks'])}"
        
        # 텔레그램 알림 발송
        await self.send_telegram(telegram_message)
        
        # 데스크톱 알림 구성
        desktop_title = f"{notification_title} - {label}"
        
        desktop_message = f"URL: {url}\n시간: {timestamp}\n경과: {elapsed_time_str}"
        
        # 날짜 정보 추가
        if target_date:
            desktop_message += f"\n날짜: {target_date}"
        
        # 시간 및 매수 정보 추가
        if page_info["stocks"]:
            desktop_message += f"\n매수 정보: {', '.join(page_info['stocks'])}"
        elif page_info["times"]:
            desktop_message += f"\n예약 가능 시간: {', '.join(page_info['times'])}"
        
        # 데스크톱 알림 발송
        self.send_desktop(desktop_title, desktop_message) 