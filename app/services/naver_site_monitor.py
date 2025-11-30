from typing import Dict, Any, Optional, List, Tuple
from app.models.monitor import MonitorTarget
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.browser_service import BrowserService
from app.services.notification_service import NotificationService
from app.utils.validators import is_naver_content_valid, is_naver_full_reservation, is_naver_page_available
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
import aiohttp
import asyncio
from app.config import logger
from app.utils.parsers import parse_time_and_stock, parse_naver_page_info, extract_date_from_url

# 한국 시간대 정의
KST = timezone(timedelta(hours=9))

class NaverSiteMonitor(AbstractSiteMonitor):
    """네이버 예약 모니터링 서비스"""

    # bizItems API 캐시 (클래스 레벨)
    _biz_items_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def __init__(self, notification_service=None, browser_service=None):
        super().__init__(notification_service)
        self.browser_service = browser_service or BrowserService()
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

    async def check_biz_items(
        self,
        page,
        business_id: str,
        biz_item_id: str,
        tag: str
    ) -> Optional[Dict[str, Any]]:
        """
        bizItems API를 호출하여 예약 가능 상태를 확인합니다.
        정각마다 갱신하고, 그 사이에는 캐시된 데이터를 사용합니다.

        Args:
            page: Playwright 페이지 객체
            business_id: 비즈니스 ID
            biz_item_id: 비즈니스 아이템 ID
            tag: 로깅용 태그

        Returns:
            dict: {"available": bool, "reason": str, "data": dict} 또는 None (오류 시)
        """
        cache_key = (business_id, biz_item_id)
        now = datetime.now(KST)

        # 캐시 확인
        if cache_key in self._biz_items_cache:
            cached = self._biz_items_cache[cache_key]
            next_check = cached["next_check"]

            # 다음 체크 시간 전이면 캐시 반환
            if now < next_check:
                logger.debug(f"[{tag}] Using cached bizItems (next check: {next_check.strftime('%H:%M:%S')})")
                return cached["result"]

        # bizItems API 호출
        logger.debug(f"[{tag}] Fetching bizItems API...")

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

            biz_items = result['data'].get('bizItems', [])

            # 다음 정각 계산
            next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

            # bizItems가 빈 배열이면 업체 비공개/운영중지
            if not biz_items:
                check_result = {"available": False, "reason": "업체 비공개 또는 운영중지", "data": None}
                self._biz_items_cache[cache_key] = {
                    "result": check_result,
                    "cached_at": now,
                    "next_check": next_hour
                }
                logger.warning(f"[{tag}] bizItems 없음 - 업체 비공개/운영중지")
                return check_result

            # 해당 아이템 찾기
            item = next((i for i in biz_items if str(i.get('bizItemId')) == str(biz_item_id)), None)

            if not item:
                check_result = {"available": False, "reason": "아이템 없음", "data": None}
                self._biz_items_cache[cache_key] = {
                    "result": check_result,
                    "cached_at": now,
                    "next_check": next_hour
                }
                logger.warning(f"[{tag}] bizItemId {biz_item_id} 없음")
                return check_result

            # bookableSettingJson 확인
            bookable_setting = item.get('bookableSettingJson', {})

            # JSON 문자열인 경우 파싱
            if isinstance(bookable_setting, str):
                try:
                    bookable_setting = json.loads(bookable_setting)
                except:
                    bookable_setting = {}

            # 일시중지 체크
            if bookable_setting.get('isPaused', False):
                check_result = {"available": False, "reason": "예약 일시중지", "data": bookable_setting}
                self._biz_items_cache[cache_key] = {
                    "result": check_result,
                    "cached_at": now,
                    "next_check": next_hour
                }
                logger.warning(f"[{tag}] 예약 일시중지")
                return check_result

            # isOpened 체크
            is_opened = bookable_setting.get('isOpened', False)

            if not is_opened:
                open_datetime_str = bookable_setting.get('openDateTime', '')
                check_result = {
                    "available": False,
                    "reason": "예약 미오픈",
                    "data": bookable_setting,
                    "openDateTime": open_datetime_str
                }
                self._biz_items_cache[cache_key] = {
                    "result": check_result,
                    "cached_at": now,
                    "next_check": next_hour
                }
                logger.warning(f"[{tag}] 예약 미오픈 (openDateTime: {open_datetime_str})")
                return check_result

            # 예약 가능!
            check_result = {"available": True, "reason": "OK", "data": bookable_setting}
            self._biz_items_cache[cache_key] = {
                "result": check_result,
                "cached_at": now,
                "next_check": next_hour
            }
            logger.debug(f"[{tag}] bizItems 예약 가능 확인 완료")
            return check_result

        except Exception as e:
            logger.error(f"[{tag}] bizItems API error: {e}")
            return None

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
    ) -> Tuple[int, List[str]]:
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
            Tuple[int, List[str]]: (새 해시값, 예약 가능 슬롯 리스트)
        """
        try:
            # URL에서 비즈니스 파라미터 추출
            url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
            url_match = re.search(url_pattern, url)
            if not url_match:
                logger.error(f"[{tag}] Could not extract business parameters from URL: {url}")
                return current_hash, current_data

            business_type_id = int(url_match.group(1))
            business_id = url_match.group(2)
            biz_item_id = url_match.group(3)

            # URL에서 날짜 추출 (startDateTime 또는 startDate)
            date_match = re.search(r'start(?:Date|DateTime)=(\d{4}-\d{2}-\d{2})', url)
            if not date_match:
                logger.error(f"[{tag}] Could not extract date from URL: {url}")
                return current_hash, current_data

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
                logger.info(f"[{tag}] {reason} - 예약 불가")
                return current_hash, []

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
                return current_hash, current_data

            # 데이터 파싱
            if result and 'data' in result:
                schedule_data = result['data']['schedule']['bizItemSchedule']
                hourly_slots = schedule_data.get('hourly', []) or []

                current_time = datetime.now(KST)
                available_slots = []

                for slot in hourly_slots:
                    # 판매일이 아니면 스킵
                    if not slot.get('isUnitSaleDay', False):
                        continue

                    # 영업일이 아니면 스킵
                    if not slot.get('isUnitBusinessDay', False):
                        continue

                    unit_stock = slot.get('unitStock', 0)
                    unit_booking_count = slot.get('unitBookingCount', 0)
                    available_count = unit_stock - unit_booking_count

                    if available_count <= 0:
                        continue

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
                    return new_hash, available_slots
                else:
                    logger.debug(f"[{tag}] No available slots")
                    return hash(str([])), []
            else:
                logger.error(f"[{tag}] Invalid API response structure")
                return current_hash, current_data

        except Exception as e:
            logger.error(f"[{tag}] Fetch API error: {e}")
            return current_hash, current_data