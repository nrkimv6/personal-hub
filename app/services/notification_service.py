import aiohttp
from plyer import notification
from datetime import datetime, timedelta
from collections import deque
import hashlib

from app.config import settings
from app.utils.validators import is_content_valid
from app.utils.parsers import parse_time_and_stock, parse_page_info

class NotificationService:
    def __init__(self):
        self.telegram_bot_token = settings.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = settings.TELEGRAM_CHAT_ID
        self.enable_desktop = settings.ENABLE_DESKTOP_NOTIFICATION
        
        # 중복 메시지 필터링을 위한 변수들
        self.recent_messages = deque(maxlen=settings.RECENT_MESSAGES_MAX)
        self.message_timestamps = {}  # 메시지 해시: 타임스탬프
        
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

    async def notify_change(self, target_id: int, url: str, label: str, content: str):
        """변경 사항을 알립니다."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 콘텐츠 유효성 검사 및 정보 파싱
        page_info = parse_page_info(content)
        
        # 텔레그램 메시지 구성
        telegram_message = (
            f"🔔 <b>변경 감지</b>\n\n"
            f"대상: {label}\n"
        )
        
        # 제목 정보 추가
        if page_info["title"]:
            telegram_message += f"제목: {page_info['title']}\n"
        
        # 기본 정보 추가
        telegram_message += (
            f"URL: {url}\n"
            f"시간: {timestamp}\n"
            f"ID: {target_id}"
        )
        
        # 시간 정보 추가
        if page_info["times"]:
            telegram_message += f"\n\n<b>예약 가능 시간:</b> {', '.join(page_info['times'])}"
        
        # 매수 정보 추가
        if page_info["stocks"]:
            telegram_message += f"\n<b>매수 정보:</b> {', '.join(page_info['stocks'])}"
        
        # 텔레그램 알림 발송
        await self.send_telegram(telegram_message)
        
        # 데스크톱 알림 구성
        desktop_title = f"변경 감지 - {label}"
        desktop_message = f"URL: {url}\n시간: {timestamp}"
        
        # 시간 및 매수 정보 추가
        if page_info["stocks"]:
            desktop_message += f"\n매수 정보: {', '.join(page_info['stocks'])}"
        elif page_info["times"]:
            desktop_message += f"\n예약 가능 시간: {', '.join(page_info['times'])}"
        
        # 데스크톱 알림 발송
        self.send_desktop(desktop_title, desktop_message) 