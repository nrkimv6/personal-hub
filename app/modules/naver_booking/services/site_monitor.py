from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field
from app.models.monitor import MonitorTarget
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.notification_service import NotificationService
from app.modules.naver_booking.utils.validators import is_naver_content_valid, is_naver_full_reservation, is_naver_page_available
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
import aiohttp
import asyncio
from app.config import settings, logger
from app.modules.naver_booking.utils.parsers import parse_time_and_stock, parse_naver_page_info
from app.utils.parsers import extract_date_from_url
from app.utils.slot_utils import is_slot_available

# 순환 참조 방지를 위한 지연 import
if TYPE_CHECKING:
    from app.services.browser_service import BrowserService

# 한국 시간대 정의
KST = timezone(timedelta(hours=9))


@dataclass
class FetchResult:
    """Fetch API 결과"""
    hash: int
    slots: List[str]
    status: str = "no_slots"  # available, no_slots, hidden, paused, closed, error
    reason: Optional[str] = None  # 상세 사유


def filter_slots_by_time_range(slots: List[str], time_range_str: Optional[str]) -> List[str]:
    """
    슬롯 리스트에서 time_range 내에 있는 슬롯만 필터링하여 반환합니다. (REQ-BOOK-002)

    Args:
        slots: 슬롯 리스트 (예: ["2025-11-30 09:00:00 (2매)", "2025-11-30 11:00:00 (1매)"])
        time_range_str: 시간 범위 문자열 (예: "10:00-21:00")

    Returns:
        list: time_range 내에 있는 슬롯만 포함된 리스트
    """
    if not time_range_str:
        return slots  # 시간 범위 필터 없으면 전체 반환

    if not slots:
        return []

    try:
        # 시간 범위 파싱
        start_str, end_str = time_range_str.split('-')
        # 24:00은 23:59로 처리 (자정까지를 의미)
        start_str_clean = start_str.strip()
        end_str_clean = end_str.strip()
        if start_str_clean == '24:00':
            start_str_clean = '23:59'
        if end_str_clean == '24:00':
            end_str_clean = '23:59'
        start_time = datetime.strptime(start_str_clean, '%H:%M').time()
        end_time = datetime.strptime(end_str_clean, '%H:%M').time()

        filtered_slots = []

        for slot in slots:
            slot_str = str(slot).lower()

            # 오전/오후 패턴 매칭
            am_pm_match = re.search(r'(오전|오후|am|pm)\s*(\d{1,2}):(\d{2})', slot_str)
            if am_pm_match:
                period = am_pm_match.group(1)
                hour = int(am_pm_match.group(2))
                minute = int(am_pm_match.group(3))

                # 24시간 형식으로 변환
                if period in ['오후', 'pm']:
                    if hour != 12:
                        hour += 12
                elif period in ['오전', 'am']:
                    if hour == 12:
                        hour = 0

                extracted_time = datetime.strptime(f"{hour:02d}:{minute:02d}", '%H:%M').time()
            else:
                # 일반 시간 패턴 (HH:MM:SS 또는 HH:MM)
                time_match = re.search(r'(\d{1,2}):(\d{2})(?::\d{2})?', str(slot))
                if not time_match:
                    continue  # 시간 파싱 불가 → 스킵

                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                extracted_time = datetime.strptime(f"{hour:02d}:{minute:02d}", '%H:%M').time()

            # 시간 범위 체크
            in_range = False
            if start_time == end_time:
                # 정확한 시간 매칭 (예: 12:00-12:00)
                in_range = extracted_time.hour == start_time.hour and extracted_time.minute == start_time.minute
            elif start_time < end_time:
                # 일반적인 시간 범위 (예: 09:00-18:00)
                in_range = start_time <= extracted_time <= end_time
            else:
                # 야간 시간 범위 (예: 22:00-06:00)
                in_range = extracted_time >= start_time or extracted_time <= end_time

            if in_range:
                filtered_slots.append(slot)
                logger.debug(f"[FILTER] ✓ 슬롯 포함: {slot} ({extracted_time} in {start_time}-{end_time})")
            # else:
                # logger.debug(f"[FILTER] ✗ 슬롯 제외: {slot} ({extracted_time} not in {start_time}-{end_time})")

        return filtered_slots

    except (ValueError, IndexError) as e:
        logger.warning(f"[FILTER] 시간 범위 파싱 오류 '{time_range_str}': {e}. 전체 슬롯 반환")
        return slots


def filter_slots_by_times(slots: List[str], target_times: Optional[List[str]]) -> List[str]:
    """
    슬롯 리스트에서 target_times 목록에 있는 시간만 필터링하여 반환합니다.

    Args:
        slots: 슬롯 리스트 (예: ["2025-11-30 09:00:00 (2매)", "2025-11-30 11:00:00 (1매)"])
               또는 dict 리스트 (예: [{"time": "09:00", ...}, {"time": "11:00", ...}])
        target_times: 목표 시간 리스트 (예: ["11:00", "13:00"])

    Returns:
        list: target_times에 해당하는 슬롯만 포함된 리스트
    """
    if not target_times:
        return slots  # 목표 시간 없으면 전체 반환

    if not slots:
        return []

    # target_times를 HH:MM 형식으로 정규화
    normalized_targets = set()
    for t in target_times:
        t_clean = t.strip()
        # HH:MM:SS → HH:MM
        if len(t_clean) == 8 and t_clean[2] == ':' and t_clean[5] == ':':
            t_clean = t_clean[:5]
        # H:MM → HH:MM
        if len(t_clean) == 4 and t_clean[1] == ':':
            t_clean = '0' + t_clean
        normalized_targets.add(t_clean)

    filtered_slots = []

    for slot in slots:
        # dict 형태 지원 (anonymous 모드에서 사용)
        if isinstance(slot, dict):
            slot_time = slot.get('time', '')
            # HH:MM 형식으로 정규화
            if len(slot_time) == 8 and slot_time[2] == ':':
                slot_time = slot_time[:5]
            if slot_time in normalized_targets:
                filtered_slots.append(slot)
                logger.debug(f"[FILTER-TIMES] ✓ 슬롯 포함: {slot} (time={slot_time})")
            continue

        # 문자열 형태
        slot_str = str(slot).lower()

        # 오전/오후 패턴 매칭
        am_pm_match = re.search(r'(오전|오후|am|pm)\s*(\d{1,2}):(\d{2})', slot_str)
        if am_pm_match:
            period = am_pm_match.group(1)
            hour = int(am_pm_match.group(2))
            minute = int(am_pm_match.group(3))

            # 24시간 형식으로 변환
            if period in ['오후', 'pm']:
                if hour != 12:
                    hour += 12
            elif period in ['오전', 'am']:
                if hour == 12:
                    hour = 0

            extracted_time = f"{hour:02d}:{minute:02d}"
        else:
            # 일반 시간 패턴 (HH:MM:SS 또는 HH:MM)
            time_match = re.search(r'(\d{1,2}):(\d{2})(?::\d{2})?', str(slot))
            if not time_match:
                continue  # 시간 파싱 불가 → 스킵

            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            extracted_time = f"{hour:02d}:{minute:02d}"

        if extracted_time in normalized_targets:
            filtered_slots.append(slot)
            logger.debug(f"[FILTER-TIMES] ✓ 슬롯 포함: {slot} (time={extracted_time})")

    return filtered_slots


@dataclass
class BizItemsCacheEntry:
    """bizItems API 캐시 엔트리 (REQ-MON-006)"""
    business_id: str                    # 캐시 키
    items: List[Dict] = field(default_factory=list)  # 전체 아이템 목록
    cached_at: datetime = field(default_factory=lambda: datetime.now(KST))
    expires_at: datetime = field(default_factory=lambda: datetime.now(KST))
    status: str = "unknown"             # "normal", "paused", "closed", "not_found", "waiting_open"

class NaverSiteMonitor(AbstractSiteMonitor):
    """네이버 예약 모니터링 서비스"""

    # bizItems API 캐시 (클래스 레벨) - business_id 단위로 캐싱 (REQ-MON-006)
    _biz_items_cache: Dict[str, BizItemsCacheEntry] = {}

    # 아이템별 상태 추적 (REQ-MON-007: 복귀 감지)
    # key: "{business_id}:{biz_item_id}", value: {"status": "not_found"|"available", "last_checked": datetime}
    _item_status_tracker: Dict[str, Dict[str, Any]] = {}

    def __init__(self, notification_service=None, browser_service=None):
        super().__init__(notification_service)
        # browser_service가 None이면 나중에 set_browser_service()로 설정
        self.browser_service = browser_service
        self.session: Optional[aiohttp.ClientSession] = None
        # URL별 해시 상태 저장
        self._url_states: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self):
        """서비스 초기화"""
        if not self.session:
            self.session = aiohttp.ClientSession()
            
    async def cleanup(self):
        """서비스 정리"""
        if self.session:
            await self.session.close()
            self.session = None
            
    async def check_status(self, target: MonitorTarget) -> Dict[str, Any]:
        """네이버 예약 페이지의 상태를 확인합니다."""
        target_id = str(target.id)
        try:
            if not self.session:
                await self.initialize()
                
            async with self.session.get(target.url) as response:
                if response.status != 200:
                    return {
                        'is_available': False,
                        'timestamp': datetime.now(),
                        'error': f'HTTP {response.status}',
                        'details': {}
                    }
                    
                html = await response.text()
                content_hash = hashlib.md5(html.encode()).hexdigest()
                
                # 네이버 예약 페이지 검증
                is_valid = is_naver_content_valid(html)
                is_full = is_naver_full_reservation(html)
                is_available = is_naver_page_available(html)
                
                # 시간대와 재고 정보 파싱
                time_and_stock = parse_time_and_stock(html)
                
                # 페이지 정보 파싱
                page_info = parse_naver_page_info(html)
                
                # URL에서 날짜 정보 추출
                date_info = extract_date_from_url(target.url)
                
                return {
                    'is_available': is_available,
                    'timestamp': datetime.now(),
                    'error': None,
                    'details': {
                        'url': target.url,
                        'status_code': response.status,
                        'content_hash': content_hash,
                        'is_valid': is_valid,
                        'is_full': is_full,
                        'time_and_stock': time_and_stock,
                        'page_info': page_info,
                        'date_info': date_info
                    }
                }
                
        except Exception as e:
            logger.error(f"Error checking status for {target_id}: {str(e)}")
            return {
                'is_available': False,
                'timestamp': datetime.now(),
                'error': str(e),
                'details': {}
            }
    
    async def handle_status_change(self, target: MonitorTarget, new_status: Dict[str, Any]) -> None:
        """상태 변경을 처리합니다."""
        if new_status.get('error'):
            logger.error(f"Status check error for {target.id}: {new_status['error']}")
            return
            
        details = new_status.get('details', {})
        is_valid = details.get('is_valid', False)
        is_full = details.get('is_full', False)
        is_available = new_status.get('is_available', False)
        
        # 시간대와 재고 정보 처리
        time_and_stock = details.get('time_and_stock', {})
        available_times = time_and_stock.get('available_times', [])
        stock_info = time_and_stock.get('stock_info', {})
        
        # 페이지 정보 처리
        page_info = details.get('page_info', {})
        venue_name = page_info.get('venue_name', '')
        venue_address = page_info.get('venue_address', '')
        
        # 날짜 정보 처리
        date_info = details.get('date_info', {})
        reservation_date = date_info.get('date', '')
        
        status_message = []
        if is_valid:
            status_message.append("유효한 페이지")
            if venue_name:
                status_message.append(f"장소: {venue_name}")
            if reservation_date:
                status_message.append(f"날짜: {reservation_date}")
            if available_times:
                status_message.append(f"예약 가능 시간: {len(available_times)}개")
                for time, stock in stock_info.items():
                    if stock > 0:
                        status_message.append(f"- {time}: {stock}석")
        else:
            status_message.append("유효하지 않은 페이지")
            
        if is_full:
            status_message.append("예약 마감")
            
        if is_available:
            status_message.append("예약 가능")
        else:
            status_message.append("예약 불가")
            
        logger.info(f"Status changed for {target.id}: {', '.join(status_message)}")
    
    async def get_interval(self, target: MonitorTarget) -> float:
        """네이버 예약 페이지 모니터링 간격을 계산합니다."""
        if target.custom_interval and target.interval is not None:
            return target.interval
        
        # 기본 간격 반환
        return 30.0  # 30초
    
    async def validate_target(self, target: MonitorTarget) -> bool:
        """네이버 예약 페이지 모니터링 대상의 유효성을 검사합니다."""
        if not target.url or not target.label:
            return False
        
        # URL 형식 검사
        if not target.url.startswith("https://booking.naver.com/"):
            return False
        
        return True
    
    async def check_availability(self, target: MonitorTarget) -> Dict[str, Any]:
        """
        네이버 예약 페이지의 가용성을 확인합니다.
        
        Args:
            target: 모니터링 대상 정보
            
        Returns:
            Dict[str, Any]: 모니터링 결과
            {
                'is_available': bool,
                'timestamp': datetime,
                'error': Optional[str],
                'details': Dict[str, Any]
            }
        """
        try:
            if not self.session:
                await self.initialize()
                
            async with self.session.get(target.url) as response:
                if response.status != 200:
                    return {
                        'is_available': False,
                        'timestamp': datetime.now(),
                        'error': f'HTTP {response.status}',
                        'details': {}
                    }
                    
                html = await response.text()
                
                # 예약 가능 여부 확인 로직
                is_available = '예약하기' in html and '예약불가' not in html
                
                return {
                    'is_available': is_available,
                    'timestamp': datetime.now(),
                    'error': None,
                    'details': {
                        'url': target.url,
                        'status_code': response.status
                    }
                }
                
        except Exception as e:
            logger.error(f"Error checking availability for {target.url}: {str(e)}")
            return {
                'is_available': False,
                'timestamp': datetime.now(),
                'error': str(e),
                'details': {}
            }
            
    async def get_monitoring_interval(self, target: MonitorTarget) -> int:
        """
        모니터링 간격을 반환합니다.

        Args:
            target: 모니터링 대상 정보

        Returns:
            int: 모니터링 간격 (초)
        """
        return target.monitoring_interval or 30  # 기본값 30초

    # ============================================================
    # Fetch API 기반 모니터링 메서드 (browser7.py에서 마이그레이션)
    # ============================================================

    def _calculate_cache_ttl(
        self,
        items: List[Dict],
        biz_item_id: Optional[str] = None,
        tag: str = ""
    ) -> Tuple[int, str]:
        """
        아이템 상태에 따라 캐시 TTL을 계산합니다. (REQ-MON-006)

        Args:
            items: bizItems API 응답의 아이템 목록
            biz_item_id: 특정 아이템 ID (옵션)
            tag: 로깅용 태그

        Returns:
            Tuple[int, str]: (TTL 초, 상태 문자열)
        """
        TTL_NORMAL = settings.BIZ_ITEMS_CACHE_TTL_NORMAL
        TTL_PAUSED = settings.BIZ_ITEMS_CACHE_TTL_PAUSED
        TTL_CLOSED = settings.BIZ_ITEMS_CACHE_TTL_CLOSED

        # 빈 배열 = 업체 비공개/운영중지
        if not items:
            logger.debug(f"[{tag}] Cache TTL: {TTL_CLOSED}s (closed)")
            return TTL_CLOSED, "closed"

        # 특정 아이템이 지정되지 않은 경우, 전체 아이템 중 가장 짧은 TTL 적용
        items_to_check = items
        if biz_item_id:
            item = next((i for i in items if str(i.get('bizItemId')) == str(biz_item_id)), None)
            if not item:
                # 아이템 없음 상태: 짧은 TTL로 복귀 감지 (REQ-MON-007)
                ttl_not_found = settings.BIZ_ITEMS_CACHE_TTL_NOT_FOUND
                logger.debug(f"[{tag}] Cache TTL: {ttl_not_found}s (not_found - 복귀 감지 모드)")
                return ttl_not_found, "not_found"
            items_to_check = [item]

        min_ttl = TTL_NORMAL
        status = "normal"
        now = datetime.now(KST)

        for item in items_to_check:
            # bookableSettingJson 파싱
            bookable = item.get('bookableSettingJson', {})
            if isinstance(bookable, str):
                try:
                    bookable = json.loads(bookable) if bookable else {}
                except json.JSONDecodeError:
                    bookable = {}

            # 일시중지 체크
            if bookable.get('isPaused', False):
                if TTL_PAUSED < min_ttl:
                    min_ttl = TTL_PAUSED
                    status = "paused"
                continue

            # 미오픈 체크 - openDateTime까지 대기 (최대 TTL_NORMAL)
            if not bookable.get('isOpened', False):
                open_dt_str = bookable.get('openDateTime', '')
                if open_dt_str:
                    try:
                        # ISO 형식 파싱 시도
                        open_dt_str_clean = open_dt_str.replace('Z', '+00:00')
                        if '+' not in open_dt_str_clean and '-' not in open_dt_str_clean[10:]:
                            # 시간대 정보 없으면 KST로 가정
                            open_dt = datetime.fromisoformat(open_dt_str_clean).replace(tzinfo=KST)
                        else:
                            open_dt = datetime.fromisoformat(open_dt_str_clean).astimezone(KST)

                        seconds_until_open = (open_dt - now).total_seconds()
                        if 0 < seconds_until_open < TTL_NORMAL:
                            # 오픈까지 남은 시간이 TTL_NORMAL보다 짧으면 그 시간 사용
                            ttl_for_open = int(seconds_until_open) + 1  # 1초 여유
                            if ttl_for_open < min_ttl:
                                min_ttl = ttl_for_open
                                status = "waiting_open"
                            logger.debug(f"[{tag}] Item waiting for open at {open_dt}, TTL: {ttl_for_open}s")
                            continue
                    except (ValueError, TypeError) as e:
                        logger.warning(f"[{tag}] Failed to parse openDateTime '{open_dt_str}': {e}")

                # openDateTime 파싱 실패 또는 없는 경우
                if TTL_NORMAL < min_ttl:
                    min_ttl = TTL_NORMAL
                    status = "not_opened"
                continue

        logger.debug(f"[{tag}] Cache TTL: {min_ttl}s ({status})")
        return min_ttl, status

    def _get_item_availability(
        self,
        items: List[Dict],
        biz_item_id: str,
        tag: str
    ) -> Optional[Dict[str, Any]]:
        """
        캐시된 아이템 목록에서 특정 아이템의 가용성을 확인합니다. (REQ-MON-006)

        Args:
            items: bizItems API 응답의 아이템 목록
            biz_item_id: 비즈니스 아이템 ID
            tag: 로깅용 태그

        Returns:
            dict: {"available": bool, "reason": str, "data": dict} 또는 None (오류 시)
        """
        # bizItems가 빈 배열이면 업체 비공개/운영중지
        if not items:
            logger.warning(f"[{tag}] bizItems 없음 - 업체 비공개/운영중지")
            return {"available": False, "reason": "업체 비공개 또는 운영중지", "data": None}

        # 해당 아이템 찾기
        item = next((i for i in items if str(i.get('bizItemId')) == str(biz_item_id)), None)

        if not item:
            logger.warning(f"[{tag}] bizItemId {biz_item_id} 없음")
            return {"available": False, "reason": "아이템 없음", "data": None}

        # bookableSettingJson 파싱
        bookable_setting = item.get('bookableSettingJson', {})
        if isinstance(bookable_setting, str):
            try:
                bookable_setting = json.loads(bookable_setting)
            except json.JSONDecodeError:
                bookable_setting = {}

        # 일시중지 체크
        if bookable_setting.get('isPaused', False):
            logger.warning(f"[{tag}] 예약 일시중지")
            return {"available": False, "reason": "예약 일시중지", "data": bookable_setting}

        # isOpened 체크
        is_opened = bookable_setting.get('isOpened', False)

        if not is_opened:
            open_datetime_str = bookable_setting.get('openDateTime', '')
            logger.warning(f"[{tag}] 예약 미오픈 (openDateTime: {open_datetime_str})")
            return {
                "available": False,
                "reason": "예약 미오픈",
                "data": bookable_setting,
                "openDateTime": open_datetime_str
            }

        # 예약 가능!
        logger.debug(f"[{tag}] bizItems 예약 가능 확인 완료")
        return {"available": True, "reason": "OK", "data": bookable_setting}

    def _track_item_status(
        self,
        business_id: str,
        biz_item_id: str,
        current_status: str,
        tag: str
    ) -> Optional[str]:
        """
        아이템 상태 변화를 추적합니다. (REQ-MON-007: 복귀 감지)

        Args:
            business_id: 업체 ID
            biz_item_id: 아이템 ID
            current_status: 현재 상태 ("not_found", "available", "paused", "closed", "not_opened")
            tag: 로깅용 태그

        Returns:
            str: 상태 변화 유형 ("appeared" = 복귀, "disappeared" = 사라짐, None = 변화 없음)
        """
        tracker_key = f"{business_id}:{biz_item_id}"
        now = datetime.now(KST)

        prev_data = self._item_status_tracker.get(tracker_key)

        if prev_data is None:
            # 최초 추적: 상태 저장
            self._item_status_tracker[tracker_key] = {
                "status": current_status,
                "last_checked": now
            }
            logger.debug(f"[{tag}] 아이템 상태 추적 시작: {current_status}")
            return None

        prev_status = prev_data.get("status")

        # 상태 변화 감지
        status_change = None

        if prev_status == "not_found" and current_status == "available":
            # 복귀 감지!
            status_change = "appeared"
            logger.info(f"[{tag}] 🔔 아이템 복귀 감지! (not_found → available)")
        elif prev_status == "available" and current_status == "not_found":
            # 사라짐 감지
            status_change = "disappeared"
            logger.info(f"[{tag}] ⚠️ 아이템 사라짐 감지 (available → not_found)")
        elif prev_status != current_status:
            # 기타 상태 변화
            logger.debug(f"[{tag}] 아이템 상태 변화: {prev_status} → {current_status}")

        # 상태 업데이트
        self._item_status_tracker[tracker_key] = {
            "status": current_status,
            "last_checked": now
        }

        return status_change

    async def _fetch_biz_items_api(
        self,
        page,
        business_id: str,
        tag: str
    ) -> Optional[Dict[str, Any]]:
        """
        bizItems GraphQL API를 호출합니다. (REQ-MON-006)

        Args:
            page: Playwright 페이지 객체
            business_id: 비즈니스 ID
            tag: 로깅용 태그

        Returns:
            dict: API 응답 또는 None (오류 시)
        """
        logger.debug(f"[{tag}] Fetching bizItems API for business_id={business_id}...")

        try:
            result = await page.evaluate("""
                async (params) => {
                    try {
                        const response = await fetch("https://booking.naver.com/graphql?opName=bizItems", {
                            "method": "POST",
                            "headers": {
                                "accept": "*/*",
                                "content-type": "application/json",
                                "sec-fetch-dest": "empty",
                                "sec-fetch-mode": "cors",
                                "sec-fetch-site": "same-origin"
                            },
                            "credentials": "include",
                            "body": JSON.stringify({
                                "operationName": "bizItems",
                                "variables": {
                                    "input": {
                                        "businessId": params.businessId,
                                        "lang": "ko",
                                        "projections": "RESOURCE"
                                    }
                                },
                                "query": "query bizItems($input: BizItemsParams) { bizItems(input: $input) { id bizItemId name startDate endDate availableStartDate isClosedBooking isClosedBookingUser bookableSettingJson bookingCountSettingJson paymentSettingJson inspectionStatusCode __typename } }"
                            })
                        });

                        if (!response.ok) {
                            const errorText = await response.text();
                            console.error('BizItems HTTP error:', response.status, errorText);
                            return { error: `HTTP ${response.status}`, details: errorText };
                        }

                        const jsonData = await response.json();

                        // GraphQL 에러 확인
                        if (jsonData.errors && jsonData.errors.length > 0) {
                            console.error('BizItems GraphQL errors:', JSON.stringify(jsonData.errors));
                            return { error: 'GraphQL Error', details: jsonData.errors };
                        }

                        return jsonData;
                    } catch (error) {
                        console.error('BizItems fetch error:', error.message, error.stack);
                        return { error: error.message, stack: error.stack };
                    }
                }
            """, {"businessId": business_id})

            # 에러 처리
            if not result:
                logger.error(f"[{tag}] bizItems API returned null")
                return None

            if 'error' in result:
                logger.error(f"[{tag}] bizItems API error: {result.get('error')}")
                logger.error(f"[{tag}] Details: {result.get('details', 'N/A')}")
                return None

            if 'data' not in result:
                logger.error(f"[{tag}] bizItems API returned invalid response (no data field)")
                return None

            return result

        except Exception as e:
            logger.error(f"[{tag}] bizItems API error: {e}")
            return None

    async def check_biz_items(
        self,
        page,
        business_id: str,
        biz_item_id: str,
        tag: str
    ) -> Optional[Dict[str, Any]]:
        """
        bizItems API를 호출하여 예약 가능 상태를 확인합니다. (REQ-MON-006)
        business_id 단위로 캐싱하여 동일 업체의 여러 아이템 모니터링 시 중복 호출 방지.

        Args:
            page: Playwright 페이지 객체
            business_id: 비즈니스 ID
            biz_item_id: 비즈니스 아이템 ID
            tag: 로깅용 태그

        Returns:
            dict: {"available": bool, "reason": str, "data": dict} 또는 None (오류 시)
        """
        now = datetime.now(KST)

        # 캐시 확인 (business_id로만 조회)
        if business_id in self._biz_items_cache:
            cached = self._biz_items_cache[business_id]

            # 캐시가 유효한 경우
            if now < cached.expires_at:
                logger.debug(f"[{tag}] Using cached bizItems for business_id={business_id} "
                           f"(expires: {cached.expires_at.strftime('%H:%M:%S')}, status: {cached.status})")
                return self._get_item_availability(cached.items, biz_item_id, tag)

        # API 호출
        result = await self._fetch_biz_items_api(page, business_id, tag)
        if result is None:
            return None

        items = result.get('data', {}).get('bizItems', [])

        # TTL 계산 및 캐싱
        ttl, status = self._calculate_cache_ttl(items, biz_item_id, tag)
        self._biz_items_cache[business_id] = BizItemsCacheEntry(
            business_id=business_id,
            items=items,
            cached_at=now,
            expires_at=now + timedelta(seconds=ttl),
            status=status
        )

        logger.info(f"[{tag}] Cached bizItems for business_id={business_id} "
                   f"(TTL: {ttl}s, status: {status}, items: {len(items)})")

        return self._get_item_availability(items, biz_item_id, tag)

    def parse_slot_datetime(self, slot: Dict[str, Any]) -> Optional[datetime]:
        """
        슬롯의 시작 시간을 파싱합니다.

        Args:
            slot: 슬롯 데이터

        Returns:
            datetime: 파싱된 시간 (KST) 또는 None
        """
        slot_datetime = None

        # unitStartTime이 있으면 먼저 시도 (로컬 시간, "YYYY-MM-DD HH:MM:SS" 형식)
        if slot.get('unitStartTime'):
            unit_start_time_str = str(slot.get('unitStartTime'))
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']:
                try:
                    slot_datetime = datetime.strptime(unit_start_time_str, fmt).replace(tzinfo=KST)
                    break
                except ValueError:
                    continue

        # unitStartTime 파싱 실패 시 unitStartDateTime 시도 (UTC ISO 형식)
        if not slot_datetime and slot.get('unitStartDateTime'):
            slot_datetime_str = str(slot.get('unitStartDateTime'))
            for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S.%f']:
                try:
                    slot_datetime = datetime.strptime(slot_datetime_str, fmt).replace(tzinfo=timezone.utc).astimezone(KST)
                    break
                except ValueError:
                    continue

        return slot_datetime

    def is_slot_in_time_range(
        self,
        slot_datetime: datetime,
        current_time: datetime,
        booking_available_hours: Optional[int] = None,
        booking_available_days: Optional[int] = None,
        tag: str = ""
    ) -> bool:
        """
        슬롯이 예약 가능 시간 범위 내인지 확인합니다.

        Args:
            slot_datetime: 슬롯 시작 시간
            current_time: 현재 시간
            booking_available_hours: N시간 후부터 예약 가능 (RI03)
            booking_available_days: N일 후부터 예약 가능 (RI02)
            tag: 로깅용 태그

        Returns:
            bool: 시간 범위 내이면 True
        """
        # 1. 과거 시간 체크
        if slot_datetime < current_time:
            logger.debug(f"[{tag}] Skipping past slot: {slot_datetime}")
            return False

        # 2. RI02 정책 체크 (N일 후부터 예약 가능)
        if booking_available_days is not None and booking_available_days > 0:
            today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            booking_threshold_date = today_start + timedelta(days=booking_available_days)
            if slot_datetime < booking_threshold_date:
                logger.debug(f"[{tag}] Skipping slot (RI02): {slot_datetime.date()} < {booking_threshold_date.date()}")
                return False

        # 3. RI03 정책 체크 (N시간 후부터 예약 가능)
        if booking_available_hours is not None and booking_available_hours > 0:
            booking_threshold_time = current_time + timedelta(hours=booking_available_hours)
            if slot_datetime < booking_threshold_time:
                logger.debug(f"[{tag}] Skipping slot (RI03): {slot_datetime} < {booking_threshold_time}")
                return False

        return True

    async def perform_task_with_fetch(
        self,
        page,
        url: str,
        tag: str,
        current_hash: int,
        current_data: List[str]
    ) -> FetchResult:
        """
        Fetch API를 사용하여 네이버 예약 상태를 모니터링합니다.
        browser7.py의 perform_task_with_fetch 함수를 마이그레이션한 것입니다.

        Args:
            page: Playwright 페이지 객체
            url: 모니터링할 URL
            tag: 로깅용 태그
            current_hash: 현재 데이터 해시값
            current_data: 현재 데이터

        Returns:
            FetchResult: 조회 결과 (hash, slots, status, reason)
        """
        try:
            # URL에서 비즈니스 파라미터 추출
            url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
            url_match = re.search(url_pattern, url)
            if not url_match:
                logger.error(f"[{tag}] Could not extract business parameters from URL: {url}")
                return FetchResult(hash=current_hash, slots=current_data, status="error", reason="URL 파싱 오류")

            business_type_id = int(url_match.group(1))
            business_id = url_match.group(2)
            biz_item_id = url_match.group(3)

            # URL에서 날짜 추출 (startDateTime 또는 startDate)
            date_match = re.search(r'start(?:Date|DateTime)=(\d{4}-\d{2}-\d{2})', url)
            if not date_match:
                logger.error(f"[{tag}] Could not extract date from URL: {url}")
                return FetchResult(hash=current_hash, slots=current_data, status="error", reason="날짜 파싱 오류")

            start_date = date_match.group(1)

            # 예약 가능 시간 정책
            booking_available_hours = None
            booking_available_days = None

            # 첫 요청인 경우 페이지를 로드하여 쿠키/세션 확보
            current_url = page.url
            if not current_url or 'booking.naver.com' not in current_url:
                logger.debug(f"[{tag}] Loading page for cookies/session: {url}")
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1000)

                # SSR 데이터에서 bookingAvailableCode 추출
                try:
                    ssr_data = await page.evaluate("""
                        () => {
                            const apolloState = window.__APOLLO_STATE__;
                            if (!apolloState) return null;

                            for (const key in apolloState) {
                                if (key.startsWith('Business:')) {
                                    const business = apolloState[key];
                                    return {
                                        bookingAvailableCode: business.bookingAvailableCode,
                                        bookingAvailableValue: business.bookingAvailableValue
                                    };
                                }
                            }
                            return null;
                        }
                    """)

                    if ssr_data:
                        code = ssr_data.get('bookingAvailableCode')
                        value = ssr_data.get('bookingAvailableValue', 0)

                        if code == 'RI03':
                            booking_available_hours = value
                            logger.debug(f"[{tag}] Booking available from {booking_available_hours}h later (RI03)")
                        elif code == 'RI02':
                            booking_available_days = value
                            logger.debug(f"[{tag}] Booking available from {booking_available_days}d later (RI02)")
                        elif code == 'RI01':
                            logger.debug(f"[{tag}] Booking available instantly (RI01)")
                except Exception as ssr_error:
                    logger.warning(f"[{tag}] Could not extract SSR booking policy: {ssr_error}")

            # bizItems API로 예약 가능 상태 확인
            biz_check = await self.check_biz_items(page, business_id, biz_item_id, tag)

            if biz_check is None:
                logger.warning(f"[{tag}] bizItems API 오류, schedule만으로 체크 진행")
            elif not biz_check["available"]:
                reason = biz_check["reason"]

                # 아이템 상태 추적 (REQ-MON-007: 복귀 감지)
                current_status = "not_found" if reason == "아이템 없음" else reason
                status_change = self._track_item_status(business_id, biz_item_id, current_status, tag)

                # 복귀 감지 시 알림 (appeared 상태일 때)
                # 이 경우는 not_found → available 이므로 여기서는 발생하지 않음
                # disappeared 등 다른 상태 변화는 로깅만

                logger.info(f"[{tag}] {reason} - 예약 불가")

                # reason을 status로 매핑
                reason_to_status = {
                    "아이템 없음": "hidden",
                    "업체 비공개 또는 운영중지": "closed",
                    "예약 일시중지": "paused",
                    "예약 미오픈": "not_opened",
                }
                status = reason_to_status.get(reason, "no_slots")
                return FetchResult(hash=current_hash, slots=[], status=status, reason=reason)
            else:
                # 예약 가능 상태 - 상태 추적
                status_change = self._track_item_status(business_id, biz_item_id, "available", tag)

                # 복귀 감지 시 알림 발송
                if status_change == "appeared":
                    logger.info(f"[{tag}] 🎉 아이템 복귀! 예약 가능 상태로 변경됨")
                    # 알림 발송
                    if self.notification_service:
                        try:
                            await self.notification_service.send_notification_message(
                                f"🔔 <b>아이템 복귀 감지!</b>\n\n"
                                f"📍 {tag}\n"
                                f"상태: 아이템 없음 → 예약 가능\n"
                                f"시각: {datetime.now(KST).strftime('%H:%M:%S')}",
                                send_desktop=True,
                                force_send=True
                            )
                        except Exception as e:
                            logger.error(f"[{tag}] 복귀 알림 발송 실패: {e}")

            # GraphQL schedule API 호출
            result = await page.evaluate("""
                async (params) => {
                    try {
                        const response = await fetch("https://booking.naver.com/graphql?opName=schedule", {
                            "method": "POST",
                            "headers": {
                                "content-type": "application/json",
                                "accept": "*/*",
                                "sec-fetch-dest": "empty",
                                "sec-fetch-mode": "cors",
                                "sec-fetch-site": "same-origin"
                            },
                            "body": JSON.stringify({
                                "operationName": "schedule",
                                "variables": {
                                    "scheduleParams": {
                                        "businessTypeId": params.businessTypeId,
                                        "businessId": params.businessId,
                                        "bizItemId": params.bizItemId,
                                        "startDateTime": params.startDateTime,
                                        "endDateTime": params.endDateTime
                                    }
                                },
                                "query": "query schedule($scheduleParams: ScheduleParams) { schedule(input: $scheduleParams) { bizItemSchedule { hourly { isBusinessDay isSaleDay isUnitBusinessDay isUnitSaleDay isHoliday unitStock unitBookingCount bookingCount stock duration minBookingCount maxBookingCount unitStartTime unitStartDateTime slotId prices { isDefault priceId agencyKey slotId scheduleId name priceTypeCode price normalPrice desc order groupName groupOrder bookingCount isImp saleStartDateTime saleEndDateTime __typename } __typename } __typename } __typename } }"
                            })
                        });

                        if (!response.ok) {
                            throw new Error(`HTTP error! status: ${response.status}`);
                        }

                        return await response.json();
                    } catch (error) {
                        console.error('Fetch error:', error);
                        return null;
                    }
                }
            """, {
                "businessTypeId": business_type_id,
                "businessId": business_id,
                "bizItemId": biz_item_id,
                "startDateTime": f"{start_date}T00:00:00",
                "endDateTime": f"{start_date}T23:59:59"
            })

            if not result:
                logger.error(f"[{tag}] Fetch API returned null")
                return FetchResult(hash=current_hash, slots=current_data, status="error", reason="API 응답 없음")

            # 데이터 파싱
            if result and 'data' in result:
                schedule_data = result['data']['schedule']['bizItemSchedule']
                hourly_slots = schedule_data.get('hourly', []) or []

                current_time = datetime.now(KST)
                available_slots = []

                for slot in hourly_slots:
                    # isUnitBusinessDay가 False면 실제 판매하지 않는 시간대이므로 스킵
                    is_unit_business_day = slot.get('isUnitBusinessDay', False)
                    if not is_unit_business_day:
                        continue

                    # 재고 확인: is_unit_business_day AND is_sale_day AND stock > 0 AND (unit_stock - unit_booking_count) > 0
                    stock = slot.get('stock', 0)
                    unit_stock = slot.get('unitStock', 0)
                    unit_booking_count = slot.get('unitBookingCount', 0)
                    is_sale_day = slot.get('isUnitSaleDay', False)

                    if not is_slot_available(stock, unit_stock, unit_booking_count, is_sale_day, is_unit_business_day):
                        continue

                    available_count = unit_stock - unit_booking_count

                    # 시간 파싱 및 범위 체크
                    slot_datetime = self.parse_slot_datetime(slot)
                    if not slot_datetime:
                        logger.warning(f"[{tag}] Could not parse slot time, skipping")
                        continue

                    if not self.is_slot_in_time_range(
                        slot_datetime, current_time,
                        booking_available_hours, booking_available_days, tag
                    ):
                        continue

                    slot_time = slot.get('unitStartTime', slot.get('unitStartDateTime', ''))
                    available_slots.append(f"{slot_time} ({available_count}매)")

                if available_slots:
                    new_hash = hash(str(available_slots))
                    logger.debug(f"[{tag}] Found {len(available_slots)} available slots")
                    return FetchResult(hash=new_hash, slots=available_slots, status="available")
                else:
                    logger.debug(f"[{tag}] No available slots")
                    return FetchResult(hash=hash(str([])), slots=[], status="no_slots")
            else:
                logger.error(f"[{tag}] Invalid API response structure")
                return FetchResult(hash=current_hash, slots=current_data, status="error", reason="API 응답 구조 오류")

        except Exception as e:
            logger.error(f"[{tag}] Fetch API error: {e}")
            return FetchResult(hash=current_hash, slots=current_data, status="error", reason=str(e))