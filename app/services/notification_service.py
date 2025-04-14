import aiohttp
from plyer import notification
from datetime import datetime, timedelta
from collections import deque
import hashlib
import re
from typing import Optional, Dict, Any, List

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
        
        # 시간별 알림 로그
        self.time_alert_log = {}  # url: {time_key: last_alert_time}
        
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
        
        # 시간 및 매수 정보 포맷팅
        formatted_times = self._format_time_info(page_info["times"])
        formatted_stocks = self._format_stock_info(page_info["stocks"])
        
        # URL 단축
        short_url = url
        if len(url) > 60:
            # URL 단축 (일부 생략)
            url_parts = url.split("?")
            if len(url_parts) > 1:
                domain = url_parts[0]
                short_url = f"{domain}?...({len(url_parts[1])}자 생략)"
                
        # 남은 날짜 계산
        target_date = extract_date_from_url(url)
        days_left_str = ""
        if target_date:
            try:
                # 날짜 형식 변환
                if "T" in target_date:
                    # ISO 형식이면 그대로 파싱
                    date_obj = datetime.fromisoformat(target_date.replace("Z", "+00:00"))
                else:
                    # YYYY-MM-DD 형식이면 시간 추가
                    date_obj = datetime.strptime(target_date + " 00:00:00", "%Y-%m-%d %H:%M:%S")
                
                # 날짜 차이 계산
                days_left = (date_obj.date() - current_time.date()).days
                
                if days_left > 0:
                    days_left_str = f" (D-{days_left})"
                elif days_left == 0:
                    days_left_str = " (D-day)"
                else:
                    days_left_str = f" (D+{abs(days_left)})"
            except:
                days_left_str = ""
        
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
            f"URL: {short_url}\n"
            f"시간: {timestamp}\n"
            f"마지막 확인 후 경과: {elapsed_time_str}\n"
            f"ID: {target_id}"
        )
        
        # 날짜 정보 추가
        if target_date:
            telegram_message += f"\n날짜: {target_date}{days_left_str}"
        
        # 시간 정보 추가
        if formatted_times:
            telegram_message += f"\n\n<b>예약 가능 시간:</b>\n{formatted_times}"
        
        # 매수 정보 추가
        if formatted_stocks:
            telegram_message += f"\n\n<b>매수 정보:</b>\n{formatted_stocks}"
            
        # 빠른 링크 추가
        telegram_message += f"\n\n<a href='{url}'>🔗 링크 열기</a>"
        
        # 텔레그램 알림 발송
        await self.send_telegram(telegram_message)
        
        # 데스크톱 알림 구성
        desktop_title = f"{notification_title} - {label}"
        
        desktop_message = f"URL: {short_url}\n시간: {timestamp}\n경과: {elapsed_time_str}"
        
        # 날짜 정보 추가
        if target_date:
            desktop_message += f"\n날짜: {target_date}{days_left_str}"
        
        # 시간 및 매수 정보 요약 추가
        if page_info["stocks"]:
            stock_summary = ", ".join([f"{time}: {stock}매" for time, stock in 
                                      zip(page_info["times"][:3], [re.search(r'(\d+)매', s).group(1) 
                                                                 if re.search(r'(\d+)매', s) else "?" 
                                                                 for s in page_info["stocks"][:3]])])
            desktop_message += f"\n매수 정보: {stock_summary}"
            if len(page_info["stocks"]) > 3:
                desktop_message += f" 외 {len(page_info['stocks']) - 3}건"
        elif page_info["times"]:
            time_summary = ", ".join(page_info["times"][:3])
            desktop_message += f"\n예약 가능 시간: {time_summary}"
            if len(page_info["times"]) > 3:
                desktop_message += f" 외 {len(page_info['times']) - 3}건"
        
        # 데스크톱 알림 발송
        self.send_desktop(desktop_title, desktop_message) 