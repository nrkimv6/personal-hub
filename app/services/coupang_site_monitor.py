import asyncio
from typing import Dict, Any, Optional, List
import logging
import json
from datetime import datetime
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.async_api import Page
from app.models.monitor_target import MonitorTarget
from app.services.notification_service import NotificationService
from app.config import settings
from app.services.abstract_site_monitor import AbstractSiteMonitor
from app.services.browser_service import BrowserService

logger = logging.getLogger(__name__)

class CoupangSiteMonitor(AbstractSiteMonitor):
    def __init__(self, notification_service=None, browser_service=None):
        super().__init__(notification_service)
        self.browser_service = browser_service or BrowserService()
        self.previous_item_statuses = {}
        self.last_check_times = {}
        self.max_retries = 3
        self.retry_delay = 10  # 초 단위 기본 대기 시간
        
        # 로그 디렉토리 설정
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
        # 모니터링 시작 시간
        self.monitoring_start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 로그 파일 설정
        self.status_log_file = self.log_dir / f"coupang_status_changes_{self.monitoring_start_time}.log"
        self.api_response_log_file = self.log_dir / f"coupang_api_response_{self.monitoring_start_time}.log"
        self.api_request_log_file = self.log_dir / f"coupang_api_request_{self.monitoring_start_time}.log"

    async def check_status(self, target: MonitorTarget, page: Page) -> Dict[str, Any]:
        """쿠팡 상품의 상태를 확인합니다."""
        current_time = datetime.now()
        logger.info(f"[쿠팡] 예약 상태 확인 중: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 상품 페이지로 이동
            product_id = self._extract_product_id(target.url)
            await page.goto(
                f"https://trip.coupang.com/tp/products/{product_id}",
                wait_until="domcontentloaded",
                timeout=60000
            )
            await page.wait_for_load_state("networkidle")
            
            # 날짜별 상태 확인
            dates = self._extract_dates(target.url)
            if not dates:
                logger.warning(f"날짜 정보를 찾을 수 없습니다: {target.url}")
                return {
                    "status": "error",
                    "timestamp": current_time.isoformat(),
                    "error": "날짜 정보를 찾을 수 없습니다"
                }
            
            status_changes = []
            current_item_statuses = {}
            
            for date in dates:
                # API 요청 수행 (재시도 로직 포함)
                vendor_items = await self._fetch_vendor_items_with_retry(page, product_id, date)
                if not vendor_items:
                    continue
                
                # 상품 상태 분석
                changes = await self._analyze_vendor_items(
                    vendor_items, 
                    date, 
                    current_time,
                    current_item_statuses
                )
                status_changes.extend(changes)
            
            # 상태 변경이 있으면 알림 발송
            if status_changes:
                await self._send_status_change_notifications(status_changes, current_time)
            
            # 현재 상태 저장
            self.previous_item_statuses = current_item_statuses
            
            return {
                "status": "success",
                "changes": status_changes,
                "timestamp": current_time.isoformat(),
                "error": None
            }
            
        except Exception as e:
            error_msg = f"쿠팡 상태 확인 중 오류 발생: {str(e)}"
            logger.error(error_msg)
            return {
                "status": "error",
                "timestamp": current_time.isoformat(),
                "error": error_msg
            }

    async def _fetch_vendor_items_with_retry(self, page: Page, product_id: str, select_date: str) -> List[Dict]:
        """재시도 로직이 포함된 vendor items 조회"""
        retry_count = 0
        
        while retry_count < self.max_retries:
            try:
                vendor_items = await self._fetch_vendor_items(page, product_id, select_date)
                if vendor_items:
                    return vendor_items
                
                retry_count += 1
                if retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** (retry_count - 1))
                    logger.warning(f"재시도 {retry_count}/{self.max_retries} - {wait_time}초 후 재시도...")
                    await asyncio.sleep(wait_time)
                    
                    # 페이지 리프레시 시도
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                        logger.info("페이지 리프레시 완료")
                    except Exception as e:
                        logger.error(f"페이지 리프레시 실패: {e}")
                
            except Exception as e:
                logger.error(f"Vendor items 조회 중 오류 발생: {e}")
                retry_count += 1
                if retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** (retry_count - 1))
                    await asyncio.sleep(wait_time)
        
        logger.error(f"최대 재시도 횟수({self.max_retries}회)를 초과했습니다.")
        return []

    def _extract_dates(self, url: str) -> List[str]:
        """URL에서 날짜 정보를 추출합니다."""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            # startDateTime 파라미터 확인
            start_date_time = query_params.get('startDateTime', [])
            if start_date_time:
                return start_date_time
            
            # startDate 파라미터 확인
            start_date = query_params.get('startDate', [])
            if start_date:
                return start_date
            
            # URL 경로에서 날짜 추출 시도
            path_parts = parsed_url.path.split('/')
            for part in path_parts:
                if len(part) == 10 and part[4] == '-' and part[7] == '-':  # YYYY-MM-DD 형식
                    return [part]
            
            logger.warning(f"URL에서 날짜 정보를 찾을 수 없습니다: {url}")
            return []
            
        except Exception as e:
            logger.error(f"날짜 추출 중 오류 발생: {e}")
            return []

    def _extract_product_id(self, url: str) -> str:
        """URL에서 상품 ID를 추출합니다."""
        try:
            parsed_url = urlparse(url)
            path_parts = parsed_url.path.split('/')
            
            # /tp/products/{product_id} 형식 확인
            if len(path_parts) >= 4 and path_parts[1] == 'tp' and path_parts[2] == 'products':
                return path_parts[3].split('?')[0]
            
            raise ValueError("올바르지 않은 쿠팡 URL 형식입니다.")
            
        except Exception as e:
            logger.error(f"상품 ID 추출 중 오류 발생: {e}")
            raise ValueError("올바르지 않은 쿠팡 URL 형식입니다.")

    async def _fetch_vendor_items(self, page: Page, product_id: str, select_date: str) -> List[Dict]:
        """쿠팡 API를 통해 vendor items 정보를 가져옵니다."""
        try:
            # API 요청 정보 로깅
            self._log_api_request(product_id, select_date)
            
            # API 요청 실행
            request_code = f"""
            (async function() {{
                try {{
                    const requestBody = {{
                        "vendorItemPackageId": "{product_id}",
                        "productType": "TICKET",
                        "selectDate": "{select_date}"
                    }};
                    
                    const requestUrl = "https://trip.coupang.com/api/products/{product_id}/vendor-items";
                    
                    const response = await fetch(requestUrl, {{
                        method: "POST",
                        headers: {{
                            "accept": "application/json, text/plain, */*",
                            "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                            "content-type": "application/json;charset=UTF-8",
                            "origin": "https://trip.coupang.com",
                            "referer": "https://trip.coupang.com/tp/products/{product_id}"
                        }},
                        credentials: "include",
                        body: JSON.stringify(requestBody)
                    }});
                    
                    if (!response.ok) {{
                        return {{ 
                            error: `HTTP error! Status: ${{response.status}}`,
                            status: response.status,
                            statusText: response.statusText
                        }};
                    }}
                    
                    const data = await response.json();
                    return data;
                }} catch (error) {{
                    return {{ error: `요청 실패: ${{error.message}}` }};
                }}
            }})()
            """
            
            result = await page.evaluate(request_code)
            
            if isinstance(result, dict) and 'error' in result:
                error_message = f"API 요청 실패: {result['error']}"
                logger.error(error_message)
                self._log_api_response(None, select_date, False, error_message)
                return []
            
            # 응답 파싱
            travel_items = result.get("travelItems", [])
            vendor_items = []
            
            for travel_item in travel_items:
                if "vendorItems" in travel_item:
                    vendor_items.extend(travel_item.get("vendorItems", []))
            
            self._log_api_response(result, select_date)
            return vendor_items
            
        except Exception as e:
            error_message = f"Vendor items 조회 중 오류 발생: {str(e)}"
            logger.error(error_message)
            self._log_api_response(None, select_date, False, error_message)
            return []

    async def _analyze_vendor_items(
        self, 
        vendor_items: List[Dict], 
        date: str,
        current_time: datetime,
        current_item_statuses: Dict
    ) -> List[Dict]:
        """Vendor items의 상태를 분석하고 변경사항을 확인합니다."""
        status_changes = []
        
        for vendor_item in vendor_items:
            vendor_item_name = vendor_item.get("vendorItemName", "알 수 없는 상품")
            sale_status = vendor_item.get("saleStatus", "알 수 없음")
            stock_count = vendor_item.get("stockCount", 0)
            
            # 상태 키 생성
            status_key = f"{date}_{vendor_item_name}"
            
            # 현재 상태 저장
            current_item_statuses[status_key] = {
                'saleStatus': sale_status,
                'stockCount': stock_count,
                'lastUpdateTime': current_time
            }
            
            # 초기 상태 설정
            if status_key not in self.previous_item_statuses:
                logger.info(f"[쿠팡] 초기 상태 저장: {date} {vendor_item_name} - {sale_status} (재고: {stock_count})")
                self.previous_item_statuses[status_key] = {
                    'saleStatus': sale_status,
                    'stockCount': stock_count,
                    'lastUpdateTime': current_time
                }
                self.last_check_times[status_key] = current_time
                continue
            
            # 상태 변경 확인
            prev_status = self.previous_item_statuses[status_key]
            
            # 판매 상태 변경
            if prev_status['saleStatus'] != sale_status:
                logger.info(f"[쿠팡] 판매 상태 변경: {date} {vendor_item_name} - {prev_status['saleStatus']} → {sale_status} (재고: {stock_count})")
                self._log_status_change(vendor_item_name, prev_status['saleStatus'], sale_status, stock_count, date)
                
                status_changes.append({
                    'date': date,
                    'vendorItemName': vendor_item_name,
                    'previous_status': prev_status['saleStatus'],
                    'current_status': sale_status,
                    'stockCount': stock_count,
                    'last_check_time': self.last_check_times.get(status_key, current_time)
                })
            
            # 재고 수량 변경
            elif prev_status['stockCount'] != stock_count:
                logger.info(f"[쿠팡] 재고 수량 변경: {date} {vendor_item_name} - {prev_status['stockCount']} → {stock_count} (상태: {sale_status})")
                
                status_changes.append({
                    'date': date,
                    'vendorItemName': vendor_item_name,
                    'previous_status': sale_status,
                    'current_status': sale_status,
                    'previous_stockCount': prev_status['stockCount'],
                    'stockCount': stock_count,
                    'stock_change_only': True,
                    'last_check_time': self.last_check_times.get(status_key, current_time)
                })
            
            # 마지막 확인 시간 업데이트
            self.last_check_times[status_key] = current_time
        
        return status_changes

    async def _send_status_change_notifications(self, status_changes: List[Dict], current_time: datetime) -> None:
        """상태 변경에 대한 알림을 발송합니다."""
        for change in status_changes:
            date = change['date']
            vendor_item_name = change['vendorItemName']
            
            # 경과 시간 계산
            elapsed_time_str = "확인 불가"
            last_check_time = change.get('last_check_time')
            if last_check_time:
                elapsed_seconds = (current_time - last_check_time).total_seconds()
                elapsed_minutes = int(elapsed_seconds // 60)
                elapsed_seconds = int(elapsed_seconds % 60)
                elapsed_time_str = f"{elapsed_minutes}분 {elapsed_seconds}초"
            
            # 메시지 생성
            if change.get('stock_change_only'):
                status_message = f"재고 변경: {change['previous_stockCount']} → {change['stockCount']}개"
            else:
                status_message = f"판매 상태: {change['previous_status']} → {change['current_status']}"
                stock_message = f"재고: {change['stockCount']}개"
            
            # 알림 메시지 생성
            message = (
                f"[쿠팡] 상태 변경: [{date}] {vendor_item_name}\n"
                f"{status_message}\n"
                f"{stock_message if not change.get('stock_change_only') else ''}\n"
                f"감지 시각: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"마지막 확인 후 경과: {elapsed_time_str}"
            )
            
            # 알림 발송
            await self.notification_service.send_notification(message)

    def _log_api_request(self, product_id: str, select_date: str) -> None:
        """API 요청 정보를 로그 파일에 기록합니다."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        request_body = {
            "vendorItemPackageId": product_id,
            "productType": "TICKET",
            "selectDate": select_date
        }
        
        log_message = (
            f"[{timestamp}] 쿠팡 API 요청 정보:\n"
            f"URL: https://trip.coupang.com/api/products/{product_id}/vendor-items\n"
            f"Method: POST\n"
            f"Request Body:\n{json.dumps(request_body, ensure_ascii=False, indent=2)}\n"
            f"{'=' * 80}\n"
        )
        
        try:
            with open(self.api_request_log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
        except Exception as e:
            logger.error(f"API 요청 로그 파일 기록 중 오류 발생: {e}")

    def _log_api_response(self, data: Optional[Dict], date: str, request_successful: bool = True, error_message: Optional[str] = None) -> None:
        """API 응답 데이터를 로그 파일에 기록합니다."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_message = (
            f"[{timestamp}] 쿠팡 API 응답 데이터 (날짜: {date}):\n"
            f"상태: {'성공' if request_successful else '실패'}\n"
        )
        
        if request_successful:
            log_message += f"응답 내용:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n"
        else:
            log_message += f"오류 메시지: {error_message}\n"
        
        log_message += f"{'=' * 80}\n"
        
        try:
            with open(self.api_response_log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
        except Exception as e:
            logger.error(f"API 응답 로그 파일 기록 중 오류 발생: {e}")

    def _log_status_change(self, item_name: str, old_status: str, new_status: str, stock_count: int, date: str) -> None:
        """상태 변경을 로그 파일에 기록합니다."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_message = (
            f"[{timestamp}] 날짜: {date}, 상품: {item_name}\n"
            f"  판매상태 변경: {old_status} → {new_status}\n"
            f"  재고수량: {stock_count}\n"
            f"{'-' * 50}\n"
        )
        
        try:
            with open(self.status_log_file, "a", encoding="utf-8") as f:
                f.write(log_message)
        except Exception as e:
            logger.error(f"로그 파일 기록 중 오류 발생: {e}")

    async def get_interval(self, target: MonitorTarget) -> float:
        """모니터링 간격을 계산합니다."""
        return settings.COUPANG_CHECK_INTERVAL  # 설정에서 가져오기

    async def validate_target(self, target: MonitorTarget) -> bool:
        """모니터링 대상의 유효성을 검사합니다."""
        if not target.url or not target.label:
            return False
            
        # 쿠팡 URL 형식 검증
        if not target.url.startswith("https://trip.coupang.com/tp/products/"):
            return False
            
        return True 