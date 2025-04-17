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

from app.config import settings, logger
from app.utils.validators import is_content_valid, is_full_reservation, is_page_available
from app.utils.parsers import parse_time_and_stock, parse_page_info, extract_date_from_url
from app.services.monitor_service import DBNotificationSettings
from app.database import SessionLocal

class NotificationService:
    def __init__(self):
        self.db = SessionLocal()
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
        settings = self.db.query(DBNotificationSettings).first()
        if not settings:
            settings = DBNotificationSettings(
                enable_telegram=True,
                enable_desktop=True,
                notify_states=json.dumps([])
            )
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        
        self.enable_telegram = settings.enable_telegram
        self.enable_desktop = settings.enable_desktop
        self.notify_states = json.loads(settings.notify_states)
        
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

    async def send_notification(self, message: str, state: str = None):
        """알림을 전송합니다."""
        if state and state not in self.notify_states:
            logger.debug(f"알림 상태 {state}가 설정에 포함되지 않아 알림을 전송하지 않습니다.")
            return
        
        if self.enable_telegram:
            await self._send_telegram(message)
        
        if self.enable_desktop:
            await self._send_desktop(message)
    
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
        # 현재 시간과 경과 시간 계산
        current_time = datetime.now()
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 마지막 확인 시간부터 현재까지의 경과 시간 계산
        elapsed_time_str = "확인 불가"
        if last_check_time:
            elapsed_seconds = (current_time - last_check_time).total_seconds()
            
            # 가독성 향상된 경과 시간 표시
            if elapsed_seconds < 60:
                elapsed_time_str = f"{int(elapsed_seconds)}초"
            elif elapsed_seconds < 3600:
                minutes = int(elapsed_seconds // 60)
                seconds = int(elapsed_seconds % 60)
                elapsed_time_str = f"{minutes}분 {seconds}초"
            else:
                hours = int(elapsed_seconds // 3600)
                minutes = int((elapsed_seconds % 3600) // 60)
                seconds = int(elapsed_seconds % 60)
                elapsed_time_str = f"{hours}시간 {minutes}분 {seconds}초"
        
        # 콘텐츠 유효성 검사 및 정보 파싱
        page_info = parse_page_info(content)
        
        # 유효성 검사 정보가 제공된 경우 사용
        if validity_info:
            # 유효성 검사 결과에 따라 상태 결정
            if validity_info.get("is_full", False):
                status = "full"
            elif not validity_info.get("is_available", True):
                status = "error"
            elif validity_info.get("is_valid", False) and validity_info.get("valid_times"):
                status = "available"
                # 유효성 검사에서 반환된 시간 정보가 있으면 사용
                if isinstance(validity_info.get("valid_times"), list):
                    page_info["times"] = validity_info["valid_times"]
            else:
                status = "change"
        else:
            # 기존 방식으로 상태 결정
            if page_info["available"] and page_info["times"]:
                status = "available"
            elif is_full_reservation(content):
                status = "full"
            elif not is_page_available(content):
                status = "error"
            else:
                status = "change"
            
        # URL 상태 업데이트 및 변경 유형 확인
        change_type = self._update_url_status(url, status)
        
        # 변경 유형에 따라 알림 발송 여부 결정
        should_notify = False
        
        # 항상 알림을 보내야 하는 상태인지 확인
        if status in settings.ALWAYS_NOTIFY_STATES:
            should_notify = True
            logger.debug(f"항상 알림 대상 상태: {status}")
        # 설정된 알림 대상 변경 유형인지 확인
        elif status in self.notify_states:
            should_notify = True
            logger.debug(f"알림 대상 변경 유형: {status}")
        else:
            logger.debug(f"알림 제외 상태: {status}")
            
        # 알림을 보내지 않는 경우 여기서 종료
        if not should_notify:
            return
            
        # 알림 제목 결정
        notification_title = self._get_notification_title(status, change_type)
        
        # 시간 정보 추가 파싱 및 처리
        additional_times_info = []
        if page_info["times"]:
            for time_text in page_info["times"]:
                time_str, stock_str = parse_time_and_stock(time_text)
                stock_int = int(stock_str) if stock_str and stock_str.isdigit() else 0
                
                if time_str:
                    info = f"{time_str}"
                    if stock_int > 0:
                        info += f": {stock_int}매"
                    additional_times_info.append(info)
        
        # 시간 및 매수 정보 포맷팅
        formatted_times = self._format_time_info(page_info["times"])
        formatted_stocks = self._format_stock_info(page_info["stocks"])
        
        # 추가 파싱 정보가 있고 기존 정보가 없는 경우 대체
        if additional_times_info and not formatted_stocks:
            formatted_stocks = self._format_stock_info(additional_times_info)
        
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
                    days_left_str = f" (D-day)"
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
        
        # 매수 정보 추가 (더 상세한 정보 있으면 사용)
        if formatted_stocks:
            telegram_message += f"\n\n<b>매수 정보:</b>\n{formatted_stocks}"
            
        # 빠른 링크 추가
        telegram_message += f"\n\n<a href='{url}'>🔗 링크 열기</a>"
        
        # 중복 메시지 확인 (향상된 버전 사용)
        if self._is_duplicate_message(telegram_message, url=url, status=status, time_info=page_info["times"]):
            print(f"중복 알림 건너뜀: {label}")
            return
        
        # 데스크톱 알림 구성
        desktop_title = f"{notification_title} - {label}"
        
        desktop_message = f"URL: {short_url}\n시간: {timestamp}\n경과: {elapsed_time_str}"
        
        # 날짜 정보 추가
        if target_date:
            desktop_message += f"\n날짜: {target_date}{days_left_str}"
        
        # 시간 및 매수 정보 요약 추가
        if page_info["stocks"] or additional_times_info:
            if page_info["stocks"]:
                stock_summary = ", ".join([f"{time}: {stock}매" for time, stock in 
                                          zip(page_info["times"][:3], [re.search(r'(\d+)매', s).group(1) 
                                                                     if re.search(r'(\d+)매', s) else "?" 
                                                                     for s in page_info["stocks"][:3]])])
            else:
                stock_summary = ", ".join(additional_times_info[:3])
                
            desktop_message += f"\n매수 정보: {stock_summary}"
            item_count = len(page_info["stocks"]) or len(additional_times_info)
            if item_count > 3:
                desktop_message += f" 외 {item_count - 3}건"
        elif page_info["times"]:
            time_summary = ", ".join(page_info["times"][:3])
            desktop_message += f"\n예약 가능 시간: {time_summary}"
            if len(page_info["times"]) > 3:
                desktop_message += f" 외 {len(page_info['times']) - 3}건"
        
        # 알림 발송 제어
        if send_telegram is None:
            # 설정값 사용
            await self._send_telegram(telegram_message)
        elif send_telegram:
            # 강제 발송
            await self._send_telegram(telegram_message)
            
        if send_desktop is None:
            # 설정값 사용
            await self._send_desktop(desktop_message)
        elif send_desktop:
            # 강제 발송
            await self._send_desktop(desktop_message) 