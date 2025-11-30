"""
네이버 예약 자동 모니터링 + GraphQL API 직접 호출 방식

browser7.py의 모니터링 기능과 GraphQL API 직접 호출을 통한 빠른 예약 시스템입니다.
버튼 클릭 대신 API를 직접 호출하여 예약 속도를 대폭 향상시킵니다.

⚠️ 주의: 이 방식은 실험적이며, GraphQL 쿼리 스키마가 필요합니다.
"""

import asyncio
import os
import time
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

# 공통 유틸리티 임포트
from old.browser_utils import initialize_browser

# browser7.py에서 필요한 함수들 임포트
sys.path.insert(0, str(Path(__file__).parent / "old"))

import importlib.util
browser7_path = Path(__file__).parent / "old" / "browser7.py"
spec = importlib.util.spec_from_file_location("browser7", browser7_path)
browser7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser7)

perform_task_with_fetch = browser7.perform_task_with_fetch
is_data_time_in_range = browser7.is_data_time_in_range
write_fetch_response_log = browser7.write_fetch_response_log
start_logging_worker = browser7.start_logging_worker
stop_logging_worker = browser7.stop_logging_worker
check_biz_items = browser7.check_biz_items
KST = browser7.KST

# url_book.py에서 예약 URL 목록 임포트
from old.url_book import booking_urls

# 설정
user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data")
profile_dir = "AutoBooking"

# 자동 예약 설정
ENABLE_AUTO_BOOKING = True
DRY_RUN_MODE = False  # True면 실제 예약 API 호출 안함

# 워커 풀 설정
NUM_WORKERS = 3  # 고정된 워커 수 (browser7.py처럼)

# 탭 관리 설정
MAX_TABS_PER_WORKER = 5
MAX_USES_PER_TAB = 50
TAB_CLEANUP_THRESHOLD = 600

# 전역 탭 풀
tab_pools = {}
tab_last_used = {}
tab_usage_counts = {}

# URL별 상태 저장 (browser7.py와 동일)
url_states = {}

# URL별 예약 락 (동시 예약 방지)
url_booking_locks = {}

# 전역 브라우저 컨텍스트 (browser7.py처럼)
browser_context = None
playwright_instance = None

# GraphQL 쿼리 캐시 (브라우저에서 캡처한 실제 쿼리)
GRAPHQL_QUERIES = {
    "schedule": """query schedule($scheduleParams: ScheduleParams) {
  schedule(input: $scheduleParams) {
    bizItemSchedule {
      hourly {
        name
        slotId
        scheduleId
        detailScheduleId
        unitStartDateTime
        unitBookingCount
        unitStock
        isBusinessDay
        isSaleDay
        isUnitSaleDay
        isUnitBusinessDay
        duration
        desc
        minBookingCount
        maxBookingCount
        saleStartDateTime
        saleEndDateTime
        seatGroups {
          color
          maxPrice
          name
          remainStock
          __typename
        }
        prices {
          groupName
          isDefault
          price
          priceId
          name
          normalPrice
          desc
          order
          groupOrder
          slotId
          agencyKey
          isImp
          saleStartDateTime
          saleEndDateTime
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}""",
    "bookingRequestSupply": None,  # 예매 양식 정보 (추후 캡처 필요)
    "account": None,  # 사용자 정보 (추후 캡처 필요)
}


async def cleanup_old_tabs(worker_id):
    """오래된 탭을 정리합니다 (browser7.py와 동일)"""
    current_time = time.time()
    tabs_to_remove = []

    if worker_id not in tab_last_used:
        return

    tab_count = len(tab_pools.get(worker_id, {}))
    print(f"[CLEANUP] Worker {worker_id} has {tab_count} tabs, MAX_TABS_PER_WORKER: {MAX_TABS_PER_WORKER}")

    if tab_count > MAX_TABS_PER_WORKER:
        print(f"[CLEANUP] Worker {worker_id} has too many tabs, checking for cleanup...")
        for tab_id, last_used in tab_last_used.get(worker_id, {}).items():
            time_since_last_use = current_time - last_used
            print(f"[CLEANUP] Tab {tab_id} last used {time_since_last_use:.1f} seconds ago (threshold: {TAB_CLEANUP_THRESHOLD})")
            if time_since_last_use > TAB_CLEANUP_THRESHOLD:
                tabs_to_remove.append(tab_id)
                print(f"[CLEANUP] Marking tab {tab_id} for removal")

    for tab_id in tabs_to_remove:
        if tab_id in tab_pools.get(worker_id, {}):
            print(f"[CLEANUP] Removing old tab {tab_id} for worker {worker_id}")
            await tab_pools[worker_id][tab_id].close()
            del tab_pools[worker_id][tab_id]
            del tab_last_used[worker_id][tab_id]
            if tab_id in tab_usage_counts.get(worker_id, {}):
                del tab_usage_counts[worker_id][tab_id]


async def get_tab(worker_id):
    """사용 가능한 탭을 가져오거나 새로 생성합니다 (browser7.py와 동일)"""
    global browser_context
    import uuid

    print(f"[GET_TAB] Worker {worker_id} requesting tab...")
    await cleanup_old_tabs(worker_id)

    if worker_id not in tab_pools:
        tab_pools[worker_id] = {}
        tab_last_used[worker_id] = {}
        tab_usage_counts[worker_id] = {}
        print(f"[GET_TAB] Initialized tab pools for worker {worker_id}")

    available_tabs = list(tab_pools[worker_id].keys())
    print(f"[GET_TAB] Worker {worker_id} has {len(available_tabs)} available tabs: {available_tabs}")

    # 탭 재사용 또는 생성 로직
    if available_tabs:
        tab_id = min(tab_last_used[worker_id].items(), key=lambda x: x[1])[0]
        tab = tab_pools[worker_id][tab_id]
        print(f"[GET_TAB] Reusing existing tab {tab_id} for worker {worker_id}")

        try:
            _ = tab.url
        except Exception as e:
            print(f"[GET_TAB] Tab {tab_id} is dead ({e}), removing and creating new one...")
            del tab_pools[worker_id][tab_id]
            del tab_last_used[worker_id][tab_id]
            if tab_id in tab_usage_counts[worker_id]:
                del tab_usage_counts[worker_id][tab_id]
            tab = await browser_context.new_page()
            tab_id = str(uuid.uuid4())
            tab_pools[worker_id][tab_id] = tab
            tab_usage_counts[worker_id][tab_id] = 0
            tab_last_used[worker_id][tab_id] = time.time()
            print(f"[GET_TAB] Created replacement tab {tab_id} for worker {worker_id}")
    elif len(tab_pools[worker_id]) < MAX_TABS_PER_WORKER:
        print(f"[GET_TAB] Creating new tab for worker {worker_id} (current: {len(tab_pools[worker_id])}, max: {MAX_TABS_PER_WORKER})")
        tab = await browser_context.new_page()
        tab_id = str(uuid.uuid4())
        tab_pools[worker_id][tab_id] = tab
        tab_usage_counts[worker_id][tab_id] = 0
        tab_last_used[worker_id][tab_id] = time.time()
        print(f"[GET_TAB] Created new tab {tab_id} for worker {worker_id}")
    else:
        tab_id = min(tab_last_used[worker_id].items(), key=lambda x: x[1])[0]
        tab = tab_pools[worker_id][tab_id]
        print(f"[GET_TAB] Reusing oldest tab {tab_id} for worker {worker_id}")

    return tab, tab_id


async def call_graphql_api(page, operation_name, variables, query):
    """
    GraphQL API를 직접 호출합니다.

    Args:
        page: Playwright 페이지 객체 (쿠키/세션 사용)
        operation_name: 작업 이름 (예: "schedule")
        variables: GraphQL 변수
        query: GraphQL 쿼리 문자열

    Returns:
        dict: API 응답 데이터
    """
    graphql_url = f"https://booking.naver.com/graphql?opName={operation_name}"

    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query
    }

    print(f"[GraphQL] Calling {operation_name}...")

    try:
        # Playwright의 evaluate를 사용하여 fetch API 호출
        response = await page.evaluate("""
            async (args) => {
                const response = await fetch(args.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify(args.payload)
                });
                return await response.json();
            }
        """, {"url": graphql_url, "payload": payload})

        # GraphQL 응답 로그 기록
        from datetime import datetime
        write_fetch_response_log(f"graphql_{operation_name}", datetime.now(KST), response)

        return response

    except Exception as e:
        print(f"[GraphQL] Error calling {operation_name}: {e}")
        return None


async def get_schedule_info(page, business_id, biz_item_id, business_type_id, target_datetime):
    """
    schedule API를 호출하여 슬롯 정보를 가져옵니다.

    Args:
        page: Playwright 페이지 객체
        business_id: 비즈니스 ID
        biz_item_id: 아이템 ID
        business_type_id: 비즈니스 타입 ID
        target_datetime: 목표 시간 (예: "2025-12-02T21:00:00+09:00")

    Returns:
        dict: 슬롯 정보 (slotId, scheduleId 등) 또는 None
    """
    if GRAPHQL_QUERIES["schedule"] is None:
        print("[GraphQL] ⚠️ schedule 쿼리가 정의되지 않았습니다!")
        return None

    # 날짜만 추출 (00:00:00으로 설정)
    from datetime import datetime
    target_dt = datetime.fromisoformat(target_datetime.replace('+09:00', ''))
    date_only = target_dt.strftime("%Y-%m-%d")
    start_datetime = f"{date_only}T00:00:00+09:00"
    end_datetime = f"{date_only}T00:00:00+09:00"

    variables = {
        "scheduleParams": {
            "businessId": business_id,
            "bizItemId": biz_item_id,
            "businessTypeId": business_type_id,
            "startDateTime": start_datetime,
            "endDateTime": end_datetime
        }
    }

    response = await call_graphql_api(
        page,
        "schedule",
        variables,
        GRAPHQL_QUERIES["schedule"]
    )

    if response and "data" in response:
        schedule_data = response["data"]["schedule"]["bizItemSchedule"]["hourly"]

        # 목표 시간을 UTC로 변환 (KST → UTC는 -9시간)
        # target_datetime은 "2025-12-02T21:00:00+09:00" 형식
        from datetime import timedelta
        target_dt_utc = target_dt - timedelta(hours=9)
        target_time_utc = target_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        print(f"[GraphQL] 목표 시간 (KST): {target_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[GraphQL] 목표 시간 (UTC): {target_time_utc}")

        for slot in schedule_data:
            slot_time = slot["unitStartDateTime"]
            if slot_time == target_time_utc:
                print(f"[GraphQL] ✓ 슬롯 찾음!")
                print(f"  - slotId: {slot['slotId']}")
                print(f"  - scheduleId: {slot['scheduleId']}")
                print(f"  - desc: {slot['desc']}")
                print(f"  - 재고: {slot['unitStock'] - slot['unitBookingCount']}/{slot['unitStock']}")
                return slot

        print(f"[GraphQL] ⚠️ 목표 시간({target_time_utc})과 일치하는 슬롯을 찾을 수 없습니다")
        print(f"[GraphQL] 사용 가능한 슬롯 (처음 3개):")
        for i, s in enumerate(schedule_data[:3]):
            # UTC를 KST로 변환하여 표시
            utc_dt = datetime.fromisoformat(s['unitStartDateTime'].replace('Z', '+00:00'))
            kst_dt = utc_dt + timedelta(hours=9)
            print(f"  [{i+1}] {kst_dt.strftime('%Y-%m-%d %H:%M')} KST ({s['desc']})")

    return None


async def perform_booking_graphql(page, url, tag, available_slots):
    """
    GraphQL API를 직접 호출하여 예약을 수행합니다.

    기존 방식:
    - 상품 상세 페이지 → 시간 선택 → 다음 버튼 → 예매 버튼 (느림)

    새 방식:
    - 상품 상세 페이지 (쿠키 획득) → GraphQL API 직접 호출 (빠름)

    Args:
        page: Playwright 페이지 객체
        url: 예약 URL
        tag: 예약 태그
        available_slots: 예약 가능한 슬롯 리스트

    Returns:
        bool: 예약 성공 여부
    """
    print(f"\n[BOOKING-GRAPHQL] {tag} 예약 시작 (GraphQL 방식)")

    if not available_slots:
        print("[BOOKING-GRAPHQL] 예약 가능한 슬롯이 없습니다.")
        return False

    # 슬롯에서 시간 추출
    first_slot = str(available_slots[0])
    import re
    time_match = re.search(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2}):(\d{2})', first_slot)
    if not time_match:
        print(f"[BOOKING-GRAPHQL] 슬롯에서 시간을 추출할 수 없습니다: {first_slot}")
        return False

    slot_date = time_match.group(1)   # 2025-12-10
    slot_hour = time_match.group(2)   # 18
    slot_minute = time_match.group(3) # 00
    slot_second = time_match.group(4) # 00

    # 오전/오후 형식으로 변환
    hour_int = int(slot_hour)
    if hour_int == 0:
        display_time = f"오전 12:{slot_minute}"
    elif hour_int < 12:
        display_time = f"오전 {hour_int}:{slot_minute}"
    elif hour_int == 12:
        display_time = f"오후 12:{slot_minute}"
    else:
        display_time = f"오후 {hour_int - 12}:{slot_minute}"

    # URL에서 비즈니스 정보 추출
    url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
    url_match = re.search(url_pattern, url)
    if not url_match:
        print(f"[BOOKING-GRAPHQL] URL에서 비즈니스 정보를 추출할 수 없습니다: {url}")
        return False

    category = url_match.group(1)
    business_id = url_match.group(2)
    item_id = url_match.group(3)

    print(f"[BOOKING-GRAPHQL] 예약 정보:")
    print(f"  - 날짜: {slot_date}")
    print(f"  - 시간: {slot_hour}:{slot_minute}")
    print(f"  - 카테고리: {category}")
    print(f"  - 비즈니스 ID: {business_id}")
    print(f"  - 아이템 ID: {item_id}")

    # 비즈니스 ID를 STEP 3에서 사용하기 위해 미리 추출
    current_business_id = business_id

    try:
        # STEP 1: /request URL 구성 (시간 자동 선택)
        print("\n[STEP 1] /request URL 구성 중 (시간 자동 선택)...")

        from urllib.parse import quote
        # 수정: 올바른 ISO 형식으로 생성
        start_datetime_param = f"{slot_date}T{slot_hour}:{slot_minute}:00+09:00"
        start_datetime_encoded = quote(start_datetime_param, safe='')

        # /request URL 구성 (시간 자동 선택)
        detail_url_with_slot = f"https://booking.naver.com/booking/{category}/bizes/{business_id}/items/{item_id}/request"
        detail_url_with_slot += f"?startDateTime={start_datetime_encoded}"

        print(f"  - URL: {detail_url_with_slot}")
        print(f"  - /request URL로 직접 접근 → 예매 페이지 바로 로드")

        # STEP 2: 예매 페이지로 직접 이동 (/request URL)
        print("\n[STEP 2] 예매 페이지 직접 이동 중...")
        await page.goto(detail_url_with_slot, wait_until="domcontentloaded")
        await asyncio.sleep(3)  # 페이지 로드 대기
        print("[STEP 2] ✓ 예매 페이지 로드 완료")

        # STEP 3: 옵션 선택 (날짜 선택 페이지에서 "다음" 버튼 활성화를 위해)
        print("\n[STEP 3] 옵션 선택 확인 중...")
        try:
            # 옵션 항목이 있는지 확인
            option_items = await page.query_selector_all('.option_item')
            if option_items and len(option_items) > 0:
                print(f"[STEP 3] 옵션 항목 {len(option_items)}개 발견")

                # 사업자 ID별 옵션 선택 로직
                if current_business_id == '1269828':
                    print(f"[STEP 3] 사업자 ID {current_business_id} - 필수 옵션 자동 선택 시도")
                    try:
                        # 첫 번째 옵션 (실방문자 정보 - 필수) 선택
                        first_option_label = await page.query_selector('.option_item:nth-of-type(1) label.option_checkbox')
                        if first_option_label:
                            # 이미 선택되어 있는지 확인
                            first_checkbox = await page.query_selector('.option_item:nth-of-type(1) input[type="checkbox"]')
                            is_checked = await first_checkbox.is_checked() if first_checkbox else False

                            if not is_checked:
                                await first_option_label.click()
                                print("[STEP 3] ✓ 첫 번째 옵션 (실방문자 정보) 선택 완료")
                                await asyncio.sleep(0.5)
                            else:
                                print("[STEP 3] ✓ 첫 번째 옵션 이미 선택됨")

                        # item_id가 6308953인 경우 추가 옵션 선택
                        if item_id == '6308953':
                            # 두 번째 옵션 (PINK MUHLY SOFT) 선택
                            second_option_label = await page.query_selector('.option_item:nth-of-type(2) label.option_checkbox')
                            if second_option_label:
                                second_checkbox = await page.query_selector('.option_item:nth-of-type(2) input[type="checkbox"]')
                                is_checked_2 = await second_checkbox.is_checked() if second_checkbox else False

                                if not is_checked_2:
                                    await second_option_label.click()
                                    print("[STEP 3] ✓ 두 번째 옵션 (PINK MUHLY SOFT) 선택 완료")
                                    await asyncio.sleep(0.3)
                                else:
                                    print("[STEP 3] ✓ 두 번째 옵션 이미 선택됨")

                            # 세 번째 옵션 (DRY LAVENDER MOOD) - 주석 처리 (필요시 활성화)
                            # third_option_label = await page.query_selector('.option_item:nth-of-type(3) label.option_checkbox')
                            # if third_option_label:
                            #     await third_option_label.click()
                            #     print("[STEP 3] ✓ 세 번째 옵션 (DRY LAVENDER MOOD) 선택 완료")
                            #     await asyncio.sleep(0.3)

                            # 네 번째 옵션 (DUSTY WOOD DEEP) - 주석 처리 (필요시 활성화)
                            # fourth_option_label = await page.query_selector('.option_item:nth-of-type(4) label.option_checkbox')
                            # if fourth_option_label:
                            #     await fourth_option_label.click()
                            #     print("[STEP 3] ✓ 네 번째 옵션 (DUSTY WOOD DEEP) 선택 완료")
                            #     await asyncio.sleep(0.3)

                    except Exception as e:
                        print(f"[STEP 3] ⚠️ 옵션 선택 중 오류: {e}")
                else:
                    print(f"[STEP 3] 사업자 ID {current_business_id} - 옵션 자동 선택 미지원")
            else:
                print("[STEP 3] 옵션 항목 없음 - 스킵")
        except Exception as e:
            print(f"[STEP 3] 옵션 확인 중 오류 (무시하고 진행): {e}")

        # STEP 4: "다음" 버튼 존재 및 활성화 여부 확인
        print("\n[STEP 4] '다음' 버튼 확인 중...")
        next_button_selectors = [
            'button.NextButton__btn_next__kfLFW',
            'button:has-text("다음")',
            'button.btn_next',
            'button[class*="btn_next"]'
        ]

        next_button_found = False
        next_button_enabled = False
        next_button = None

        for selector in next_button_selectors:
            try:
                next_button = await page.wait_for_selector(selector, timeout=2000)
                if next_button:
                    next_button_found = True

                    # 버튼이 활성화되어 있는지 확인 (여러 방법)
                    is_disabled_attr = await next_button.get_attribute('disabled')
                    class_name = await next_button.get_attribute('class')

                    # NextButton__disabled__ 클래스 확인 (동적으로 변하는 해시 포함)
                    has_disabled_class = 'NextButton__disabled__' in (class_name or '')

                    next_button_enabled = (is_disabled_attr is None and not has_disabled_class)

                    print(f"[STEP 4] '다음' 버튼 찾음 (선택자: {selector})")
                    print(f"[STEP 4] - class: {class_name}")
                    print(f"[STEP 4] - disabled 속성: {is_disabled_attr}")
                    print(f"[STEP 4] - disabled 클래스: {has_disabled_class}")
                    print(f"[STEP 4] - 활성화 여부: {next_button_enabled}")
                    break
            except:
                continue

        # "다음" 버튼이 없거나 비활성화된 경우 → 수동 선택 모드
        if not next_button_found or not next_button_enabled:
            print(f"[STEP 4] ⚠️ '다음' 버튼이 {'없거나' if not next_button_found else '비활성화되어 있습니다'}!")
            print(f"[STEP 4] 수동 시간 선택 모드로 전환합니다...")

            # STEP 4-1: 날짜 선택 확인
            print("\n[STEP 4-1] 날짜 선택 확인 중...")
            try:
                # 이미 선택된 날짜가 있는지 확인
                selected_date = await page.query_selector('button.calendar_date.selected')
                if selected_date:
                    date_text = await selected_date.inner_text()
                    print(f"[STEP 4-1] ✓ 이미 선택된 날짜: {date_text}")
                else:
                    # 날짜 선택 필요
                    print(f"[STEP 4-1] 날짜를 선택해야 합니다: {slot_date}")
                    # slot_date에서 일(day)만 추출
                    from datetime import datetime
                    date_obj = datetime.strptime(slot_date, "%Y-%m-%d")
                    day_str = str(date_obj.day)

                    # 날짜 버튼 찾기 (매진되지 않은 것만)
                    date_buttons = await page.query_selector_all('button.calendar_date:not(.unselectable)')
                    date_selected = False
                    for btn in date_buttons:
                        btn_text = await btn.inner_text()
                        if btn_text.strip() == day_str:
                            await btn.click()
                            print(f"[STEP 4-1] ✓ 날짜 선택 완료: {day_str}일")
                            date_selected = True
                            await asyncio.sleep(1)  # 시간 슬롯 로드 대기
                            break

                    if not date_selected:
                        print(f"[STEP 4-1] ⚠️ 날짜({day_str}일)를 찾을 수 없습니다.")
                        return False
            except Exception as e:
                print(f"[STEP 4-1] 날짜 선택 오류: {e}")

            # STEP 4-2: 시간 선택
            print(f"\n[STEP 4-2] 시간 선택 중... (목표: {display_time})")
            try:
                # 시간 슬롯 로드 대기
                await asyncio.sleep(2)

                # 시간 버튼 찾기 - 정확한 선택자 사용
                time_buttons = await page.query_selector_all('button.btn_time')
                time_selected = False

                print(f"[STEP 4-2] 발견된 시간 버튼 수: {len(time_buttons)}")

                if len(time_buttons) == 0:
                    print(f"[STEP 4-2] ⚠️ 시간 버튼을 찾을 수 없습니다. 페이지 로딩 대기 중...")
                    await asyncio.sleep(3)
                    time_buttons = await page.query_selector_all('button.btn_time')
                    print(f"[STEP 4-2] 재시도 후 발견된 시간 버튼 수: {len(time_buttons)}")

                for idx, btn in enumerate(time_buttons):
                    btn_text = await btn.inner_text()
                    # innerText는 "오후 6:00\n2매" 형식일 수 있으므로 줄바꿈 제거
                    btn_text_clean = btn_text.replace('\n', ' ').strip()

                    # "오후 6:00" 부분만 추출 (숫자 앞까지)
                    # "오후 6:00 2매" → "오후 6:00"
                    import re
                    time_part_match = re.match(r'(오전|오후)\s+\d+:\d+', btn_text_clean)

                    print(f"[STEP 4-2] [{idx}] 버튼 텍스트: '{btn_text_clean}' (원본: '{btn_text}')")

                    if time_part_match:
                        time_part = time_part_match.group(0)
                        print(f"[STEP 4-2] [{idx}] 추출된 시간: '{time_part}' vs 목표: '{display_time}' → 일치: {time_part == display_time}")

                        if time_part == display_time:
                            # aria-selected가 false인지 확인 (선택 가능한지)
                            aria_selected = await btn.get_attribute('aria-selected')
                            print(f"[STEP 4-2] [{idx}] ✓ 시간 일치! aria-selected: {aria_selected}")

                            if aria_selected == 'false':
                                await btn.click()
                                print(f"[STEP 4-2] ✓ 시간 선택 완료: {btn_text_clean}")
                                time_selected = True
                                await asyncio.sleep(1)
                                break
                            else:
                                print(f"[STEP 4-2] ⚠️ 시간은 일치하지만 선택 불가 (aria-selected: {aria_selected})")
                    else:
                        print(f"[STEP 4-2] [{idx}] 정규식 매칭 실패")

                if not time_selected:
                    print(f"[STEP 4-2] ⚠️ 목표 시간({display_time})을 찾을 수 없습니다.")
                    # 사용 가능한 시간 목록 출력
                    available_times_list = []
                    for btn in time_buttons:
                        btn_text = await btn.inner_text()
                        aria_selected = await btn.get_attribute('aria-selected')
                        available_times_list.append(f"{btn_text.replace(chr(10), ' ')} (aria-selected: {aria_selected})")
                    print(f"[STEP 4-2] 사용 가능한 시간: {', '.join(available_times_list)}")
                    return False

            except Exception as e:
                print(f"[STEP 4-2] 시간 선택 오류: {e}")
                import traceback
                traceback.print_exc()
                return False

            # STEP 4-3: "다음" 버튼 다시 찾기 및 클릭
            print("\n[STEP 4-3] '다음' 버튼 다시 확인 중...")
            next_button = None
            for selector in next_button_selectors:
                try:
                    next_button = await page.wait_for_selector(selector, timeout=3000)
                    if next_button:
                        print(f"[STEP 4-3] ✓ '다음' 버튼 찾음 (선택자: {selector})")
                        break
                except:
                    continue

            if not next_button:
                print("[STEP 4-3] ⚠️ '다음' 버튼을 찾을 수 없습니다. 예약 실패")
                return False

        # "다음" 버튼 클릭
        print("\n[STEP 4-FINAL] '다음' 버튼 클릭...")
        current_url_before_click = page.url
        await next_button.click()
        print("[STEP 4-FINAL] ✓ '다음' 버튼 클릭 완료")

        # URL이 변경되었는지 확인 (리다이렉트될 수 있음)
        await asyncio.sleep(3)
        current_url_after_click = page.url

        if current_url_before_click != current_url_after_click:
            print(f"[STEP 4-FINAL] URL 변경 감지: {current_url_before_click} → {current_url_after_click}")
        else:
            print(f"[STEP 4-FINAL] URL 변경 없음 (현재: {current_url_after_click})")

        print("[STEP 4-FINAL] ✓ 페이지 전환 완료")

        # STEP 5: 필수 입력 필드 확인 및 자동 입력
        print("\n[STEP 5] 필수 입력 필드 확인 중...")
        print(f"[STEP 5] 사업자 ID: {current_business_id}")

        auto_fill_success = False

        # === 사업자 ID별 자동 입력 로직 ===

        # 1. 사업자 ID 142806 (전통주갤러리)
        if current_business_id == '142806':
            print(f"[STEP 5] 🤖 사업자 ID {current_business_id} 감지 - 전통주갤러리 자동 입력 시도 중...")
            try:
                # 1) 첫 번째 드롭다운 - 상세정보 동의
                print("[STEP 5-1] 첫 번째 드롭다운 선택 중...")
                first_dropdown = await page.query_selector('button.select_btn')
                if first_dropdown:
                    await first_dropdown.click()
                    await asyncio.sleep(0.5)
                    # 두 번째 항목 선택 (nth(1) = 인덱스 1)
                    await page.locator('button.select_item').nth(1).click()
                    print("[STEP 5-1] ✓ 첫 번째 드롭다운 선택 완료")
                    await asyncio.sleep(0.3)

                # 2) 두 번째 드롭다운 - 동의서 확인
                print("[STEP 5-2] 두 번째 드롭다운 선택 중...")
                second_dropdown = await page.locator('button.select_btn').nth(1).element_handle()
                if second_dropdown:
                    await second_dropdown.click()
                    await asyncio.sleep(0.5)
                    await page.locator('button.select_item').nth(1).click()
                    print("[STEP 5-2] ✓ 두 번째 드롭다운 선택 완료")
                    await asyncio.sleep(0.3)

                # 3) 예매자 이름 가져오기
                print("[STEP 5-3] 예매자 이름 추출 중...")
                user_name_element = await page.query_selector('.booking_user_detail div.name')
                if user_name_element:
                    user_name = await user_name_element.inner_text()
                    user_name = user_name.strip()
                    print(f"[STEP 5-3] 예매자 이름: {user_name}")

                    # 4) 성함 입력
                    print("[STEP 5-4] 성함 입력 중...")
                    textarea = await page.query_selector('textarea#extra2')
                    if textarea:
                        await textarea.fill(user_name)
                        print(f"[STEP 5-4] ✓ 성함 입력 완료: {user_name}")
                        await asyncio.sleep(0.5)

                        print("[STEP 5] ✅ 자동 입력 완료 (사업자 ID 142806)!")
                        auto_fill_success = True
                    else:
                        print("[STEP 5-4] ⚠️ textarea#extra2를 찾을 수 없습니다.")
                else:
                    print("[STEP 5-3] ⚠️ 예매자 이름을 찾을 수 없습니다.")

            except Exception as e:
                print(f"[STEP 5] ⚠️ 자동 입력 실패 (사업자 ID 142806): {e}")

        # 2. 사업자 ID 1269828
        elif current_business_id == '1269828':
            # 입력 필드가 있는지 확인
            input_fields = await page.query_selector_all('input[required], textarea[required]')
            if input_fields and len(input_fields) > 0:
                print(f"[STEP 5] ⚠️ 필수 입력 필드가 {len(input_fields)}개 있습니다!")
                print(f"[STEP 5] 🤖 사업자 ID {current_business_id} 감지 - 자동 입력 시도 중...")
                try:
                    # 예매자 이름 가져오기 (142806과 동일한 방법)
                    user_name = None
                    user_name_element = await page.query_selector('.booking_user_detail div.name')
                    if user_name_element:
                        user_name = await user_name_element.inner_text()
                        user_name = user_name.strip()
                        print(f"[STEP 5] 예매자 이름: {user_name}")
                    else:
                        print(f"[STEP 5] ⚠️ 예매자 이름을 찾을 수 없습니다. 기본값 사용")
                        user_name = '김나랑'  # 폴백 기본값

                    # placeholder로 입력란 찾기
                    placeholder_inputs = await page.query_selector_all('input[placeholder="내용을 입력해주세요."]')

                    if len(placeholder_inputs) >= 4:
                        print(f"[STEP 5] 입력란 {len(placeholder_inputs)}개 발견")

                        # 1번째: 실방문자 성함 (예매자 이름 자동 사용)
                        await placeholder_inputs[0].fill(user_name)
                        print(f"[STEP 5] ✓ 1번째 입력란: {user_name}")
                        await asyncio.sleep(0.3)

                        # 2번째: 전화번호 뒷자리
                        await placeholder_inputs[1].fill('4216')
                        print("[STEP 5] ✓ 2번째 입력란: 4216")
                        await asyncio.sleep(0.3)

                        # 3번째: 네
                        await placeholder_inputs[2].fill('네')
                        print("[STEP 5] ✓ 3번째 입력란: 네")
                        await asyncio.sleep(0.3)

                        # 4번째: 네
                        await placeholder_inputs[3].fill('네')
                        print("[STEP 5] ✓ 4번째 입력란: 네")
                        await asyncio.sleep(0.5)

                        print("[STEP 5] ✅ 자동 입력 완료 (사업자 ID 1269828)!")
                        auto_fill_success = True

                    else:
                        print(f"[STEP 5] ⚠️ 예상과 다른 입력란 개수: {len(placeholder_inputs)}개 (예상: 4개)")

                except Exception as e:
                    print(f"[STEP 5] ⚠️ 자동 입력 실패 (사업자 ID 1269828): {e}")
                    import traceback
                    traceback.print_exc()

        # === 자동 입력 실패 시 처리 ===
        if not auto_fill_success:
            # 필수 입력 필드가 있는지 확인
            input_fields = await page.query_selector_all('input[required], textarea[required]')
            select_buttons = await page.query_selector_all('button.select_btn')

            if (input_fields and len(input_fields) > 0) or (select_buttons and len(select_buttons) > 0):
                total_fields = len(input_fields) + len(select_buttons)
                print(f"[STEP 5] ⚠️ 자동 입력 실패 또는 미지원 사업자")
                print(f"[STEP 5] 필수 입력 필드 {total_fields}개 (input/textarea: {len(input_fields)}, select: {len(select_buttons)})")
                print("[STEP 5] 사용자가 직접 입력할 때까지 대기합니다...")

                # 텔레그램 알림
                from old.telegram_message import send_telegram_notification
                current_url = page.url
                notify_msg = f"⚠️ [{tag}] 예약 페이지가 열렸습니다!\n\n"
                notify_msg += f"필수 입력 필드 {total_fields}개를 입력하고 예매 버튼을 눌러주세요.\n"
                notify_msg += f"사업자 ID: {current_business_id}\n"
                notify_msg += f"URL: {current_url}"
                await send_telegram_notification(notify_msg)

                # 브라우저 창을 활성화하여 사용자 주목
                print("[STEP 5] 💡 브라우저 창에서 필수 정보를 입력하세요!")
                print("[STEP 5] 입력 완료 후 예매 버튼을 누르면 자동으로 진행됩니다.")
                print("[STEP 5] (또는 60초 후 자동으로 버튼 클릭 시도)")

                # 60초 대기 (사용자가 입력할 시간)
                await asyncio.sleep(60)
            else:
                print("[STEP 5] ✓ 필수 입력 필드 없음 (바로 예약 가능)")

        # STEP 6: 예매 버튼 활성화 대기 및 클릭
        print("\n[STEP 6] 예매 버튼 활성화 대기 중...")

        # wait_for_button_enabled 사용 (browser_utils.py)
        from old.browser_utils import wait_for_button_enabled
        is_enabled = await wait_for_button_enabled(page, timeout=10000)

        if not is_enabled:
            print("[STEP 6] ⚠️ 예매 버튼이 활성화되지 않았습니다.")
            print("[STEP 6] 필수 입력이 완료되지 않았거나 다른 문제가 있을 수 있습니다.")
            return False

        print("[STEP 6] ✓ 예매 버튼 활성화됨!")

        # STEP 7: 예매 버튼 클릭
        print("\n[STEP 7] 예매 버튼 클릭 준비...")

        if DRY_RUN_MODE:
            print("⚠️  [DRY RUN MODE] 실제 예매를 진행하지 않습니다 (테스트 모드)")
            print("실제 예매를 진행하려면 DRY_RUN_MODE = False로 설정하세요!")
            print(f"  - 예매 버튼 상태: 활성화됨")
        else:
            # 실제 예매 버튼 클릭
            await page.click('button.btn_request')
            print("[STEP 7] ✅ 예매 버튼 클릭 완료!")
            await asyncio.sleep(3)

        print("\n[SUCCESS] 예약 프로세스 완료!")
        return True

    except Exception as e:
        print(f"[ERROR] 예약 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


async def worker_task(url, tag, worker_id, url_info):
    """
    개별 워커 태스크 (browser7.py의 worker_task와 유사)
    """
    start_time = datetime.now(KST)
    start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"Worker {worker_id}: processing task : {tag} at {start_time_str}")

    # URL 상태 가져오기
    if url not in url_states:
        url_states[url] = {
            "hash": None,
            "data": [],
            "last_check_time": start_time,
            "last_notified_hash": None,
            "booking_count": 0
        }

    current_hash = url_states[url].get("hash")
    current_data = url_states[url].get("data", [])
    last_check_time = url_states[url].get("last_check_time", start_time)
    last_notified_hash = url_states[url].get("last_notified_hash")
    booking_count = url_states[url].get("booking_count", 0)

    time_range = url_info.get("time_range")
    max_bookings = url_info.get("max_bookings", None)

    # 최대 예약 수 도달 체크
    if max_bookings and booking_count >= max_bookings:
        print(f"Worker {worker_id}: [{tag}] ✅ 최대 예약 수({max_bookings}회) 도달! 스킵")
        return tag

    tab, tab_id = await get_tab(worker_id)

    try:
        # Fetch API로 예약 가능 여부 확인 (browser7.py와 동일)
        new_hash, new_data = await perform_task_with_fetch(
            tab, url, tag, current_hash, current_data,
            validate_level=2, last_check_time=last_check_time
        )

        if new_hash is not None:
            # 데이터 해시 계산
            if new_data:
                data_hash = hashlib.md5(str(new_data).encode('utf-8')).hexdigest()
            else:
                data_hash = hashlib.md5(b'').hexdigest()

            # 변경 감지 및 알림
            if data_hash != last_notified_hash:
                # 빈 데이터인 경우
                if not new_data or (isinstance(new_data, list) and len(new_data) == 0):
                    print(f"Worker {worker_id}: [{tag}] Data is empty, updating state only")
                    url_states[url]["hash"] = new_hash
                    url_states[url]["data"] = new_data
                    url_states[url]["last_check_time"] = datetime.now(KST)
                    url_states[url]["last_notified_hash"] = data_hash
                else:
                    # 데이터가 있는 경우
                    print(f"Worker {worker_id}: [{tag}] ✅ 예약 가능 감지!")
                    print(f"Worker {worker_id}: [{tag}] 슬롯: {new_data}")

                    # 시간 범위 필터링
                    in_range = is_data_time_in_range(new_data, time_range) if time_range else True

                    if in_range:
                        # === 예약 시도 전 Lock 획득 (동시 예약 방지) ===
                        if url not in url_booking_locks:
                            url_booking_locks[url] = asyncio.Lock()

                        # Lock 획득 시도 (이미 다른 워커가 예약 중이면 대기하지 않고 스킵)
                        lock_acquired = url_booking_locks[url].locked()
                        if lock_acquired:
                            print(f"Worker {worker_id}: [{tag}] ⚠️ 다른 워커가 이미 예약 중... 스킵")
                            return tag

                        async with url_booking_locks[url]:
                            # Lock 획득 후 다시 한번 max_bookings 체크
                            current_booking_count = url_states[url].get("booking_count", 0)
                            if max_bookings and current_booking_count >= max_bookings:
                                print(f"Worker {worker_id}: [{tag}] ✅ 최대 예약 수({max_bookings}회) 이미 도달! 스킵")
                                return tag

                            # 텔레그램 알림
                            from old.telegram_message import send_telegram_notification
                            message = f"🎯 [{tag}] 예약 가능! (GraphQL 방식)\n\n"
                            message += f"슬롯: {', '.join(str(slot) for slot in new_data)}\n"
                            if time_range:
                                message += f"시간 범위: {time_range}\n"
                            message += f"URL: {url}\n\n"

                            if ENABLE_AUTO_BOOKING:
                                message += "🤖 GraphQL API로 자동 예약을 시도합니다..."
                                await send_telegram_notification(message)

                                print(f"Worker {worker_id}: [{tag}] 🔒 탭 독점 + 예약 락 획득 - 예약 시작")

                                # GraphQL 방식으로 자동 예약
                                booking_success = await perform_booking_graphql(tab, url, tag, new_data)

                                if booking_success:
                                    # 예약 성공 카운터 증가
                                    url_states[url]["booking_count"] = url_states[url].get("booking_count", 0) + 1
                                    current_count = url_states[url]["booking_count"]

                                    success_msg = f"✅ [{tag}] GraphQL 자동 예약 {'시뮬레이션' if DRY_RUN_MODE else ''} 완료!\n"
                                    if max_bookings:
                                        success_msg += f"예약 성공: {current_count}/{max_bookings}회"
                                    else:
                                        success_msg += f"예약 성공: {current_count}회 (무제한)"
                                    print(f"Worker {worker_id}: {success_msg}")
                                    await send_telegram_notification(success_msg)
                                else:
                                    fail_msg = f"❌ [{tag}] GraphQL 자동 예약 실패"
                                    print(f"Worker {worker_id}: {fail_msg}")
                                    await send_telegram_notification(fail_msg)

                                # 탭 교체
                                print(f"Worker {worker_id}: [{tag}] 🔓 탭 독점 해제")
                                try:
                                    await tab.close()
                                except:
                                    pass
                                if worker_id in tab_pools and tab_id in tab_pools[worker_id]:
                                    del tab_pools[worker_id][tab_id]
                                if worker_id in tab_last_used and tab_id in tab_last_used[worker_id]:
                                    del tab_last_used[worker_id][tab_id]
                                if worker_id in tab_usage_counts and tab_id in tab_usage_counts[worker_id]:
                                    del tab_usage_counts[worker_id][tab_id]
                            else:
                                message += "ℹ️ 자동 예약이 비활성화되어 있습니다."
                                await send_telegram_notification(message)
                        # Lock은 여기서 자동으로 해제됨 (async with 종료)

                        # 상태 업데이트
                        url_states[url] = {
                            "hash": new_hash,
                            "data": new_data,
                            "last_check_time": datetime.now(KST),
                            "last_notified_hash": data_hash,
                            "booking_count": url_states[url].get("booking_count", 0)
                        }
                        print(f"Worker {worker_id}: New change for {tag} is in time range. Notification sent.")
                    else:
                        print(f"Worker {worker_id}: [{tag}] ⏭️ 시간 범위 밖 슬롯")
                        url_states[url]["hash"] = new_hash
                        url_states[url]["data"] = new_data
                        url_states[url]["last_check_time"] = datetime.now(KST)
            else:
                url_states[url]["hash"] = new_hash
                url_states[url]["last_check_time"] = datetime.now(KST)
        else:
            if url in url_states:
                url_states[url]["last_check_time"] = datetime.now(KST)

    except Exception as e:
        error_msg = str(e)
        print(f"Worker {worker_id}: Error in worker_task: {error_msg}")

        # 심각한 오류인 경우만 탭 교체
        serious_errors = [
            "Browser is not connected",
            "Target page, context or browser has been closed",
            "Protocol error",
            "Connection lost"
        ]

        is_serious_error = any(error in error_msg for error in serious_errors)

        if is_serious_error:
            print(f"Serious browser error detected. Replacing tab {tab_id}.")
            if tab:
                try:
                    await tab.close()
                except:
                    pass
            if tab_id in tab_pools.get(worker_id, {}):
                del tab_pools[worker_id][tab_id]
            if tab_id in tab_last_used.get(worker_id, {}):
                del tab_last_used[worker_id][tab_id]
            if tab_id in tab_usage_counts.get(worker_id, {}):
                del tab_usage_counts[worker_id][tab_id]
        else:
            print(f"Minor error. Keeping tab {tab_id} for reuse.")

    # 탭 사용 통계 업데이트
    if worker_id in tab_pools and tab_id in tab_pools[worker_id]:
        tab_last_used[worker_id][tab_id] = time.time()
        current_usage = tab_usage_counts[worker_id].get(tab_id, 0) + 1
        tab_usage_counts[worker_id][tab_id] = current_usage
        print(f"Tab {tab_id} (worker {worker_id}) used {current_usage} times.")

        # 탭 사용 횟수 제한에 도달하면 교체
        if current_usage >= MAX_USES_PER_TAB:
            print(f"Tab {tab_id} reached max uses ({MAX_USES_PER_TAB}). Replacing for memory management.")
            if tab:
                try:
                    await tab.close()
                except:
                    pass
            if tab_id in tab_pools.get(worker_id, {}):
                del tab_pools[worker_id][tab_id]
            if tab_id in tab_last_used.get(worker_id, {}):
                del tab_last_used[worker_id][tab_id]
            if tab_id in tab_usage_counts.get(worker_id, {}):
                del tab_usage_counts[worker_id][tab_id]

    end_time = datetime.now(KST)
    processing_time = (end_time - start_time).total_seconds()
    print(f"Worker {worker_id}: completed task : {tag}, took {processing_time:.2f} seconds")

    return tag


async def worker(task_queue, worker_id):
    """워커가 큐에서 태스크를 계속 처리합니다 (browser7.py와 동일)"""
    while True:
        try:
            # 큐에서 태스크 가져오기
            task = await task_queue.get()
            url, tag, url_info = task

            if url is None:  # 종료 신호
                print(f"Worker {worker_id}: Shutting down")
                task_queue.task_done()
                break

            # 태스크 처리
            await worker_task(url, tag, worker_id, url_info)

            # 태스크 완료 표시
            task_queue.task_done()

        except Exception as e:
            print(f"Worker {worker_id} encountered an error: {e}")
            if 'task_queue' in locals():
                task_queue.task_done()
            await asyncio.sleep(1)


async def task_scheduler(booking_urls, task_queue):
    """태스크 스케줄러 (browser7.py의 improved_task_scheduler와 유사)"""
    import heapq
    import random

    print(f"[SCHEDULER] Initializing scheduler with {len(booking_urls)} URLs")
    next_run_times = []

    for index, url_info in enumerate(booking_urls):
        url = url_info["url"]
        tag = url_info["tag"]

        # 첫 실행은 바로 시작 (0~5초 랜덤)
        initial_interval = random.uniform(0, 5)
        next_run = time.time() + initial_interval
        heapq.heappush(next_run_times, (next_run, index))
        print(f"[SCHEDULER] Scheduled {tag} to run in {initial_interval:.2f} seconds")

    print(f"[SCHEDULER] Starting main loop...")
    while True:
        now = time.time()
        if next_run_times and next_run_times[0][0] <= now:
            next_run, url_index = heapq.heappop(next_run_times)

            url_info = booking_urls[url_index]
            url = url_info["url"]
            tag = url_info["tag"]

            # 큐에 태스크 추가
            await task_queue.put((url, tag, url_info))

            # 다음 실행 시간 계산 (5~10초 간격)
            interval = random.uniform(5, 10)
            next_run = now + interval
            heapq.heappush(next_run_times, (next_run, url_index))

            print(f"Scheduled task for {tag} with interval {interval:.2f} seconds.")
        else:
            # 대기할 태스크가 없으면 짧은 슬립
            await asyncio.sleep(0.1)


async def main():
    """메인 실행 함수 (browser7.py 스타일의 워커 풀 방식)"""
    global browser_context, playwright_instance

    print("=" * 60)
    print("네이버 예약 자동 모니터링 + GraphQL API 직접 호출 시스템")
    print("=" * 60)
    start_time_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"시작 시간: {start_time_str}")
    print(f"모니터링 URL 수: {len(booking_urls)}")
    print(f"워커 수: {NUM_WORKERS} (고정)")
    print(f"최대 탭 수: {NUM_WORKERS * MAX_TABS_PER_WORKER}개 ({NUM_WORKERS}워커 × {MAX_TABS_PER_WORKER}탭)")
    print(f"자동 예약: {'활성화' if ENABLE_AUTO_BOOKING else '비활성화'}")
    print(f"실행 모드: {'DRY RUN (시뮬레이션)' if DRY_RUN_MODE else 'LIVE (실제 예약)'}")
    print("=" * 60)
    print()

    # 로깅 워커 스레드 시작
    start_logging_worker()
    print("[MAIN] Logging worker started")

    # 브라우저 초기화
    browser_context, playwright_instance = await initialize_browser(
        user_data_dir=user_data_dir,
        profile_dir=profile_dir,
        headless=False
    )
    print(f"[MAIN] Browser context initialized")

    # 태스크 큐 생성
    task_queue = asyncio.Queue()

    # 고정된 워커 풀 생성 (browser7.py처럼)
    worker_tasks = []
    for i in range(NUM_WORKERS):
        worker_task = asyncio.create_task(worker(task_queue, i + 1))
        worker_tasks.append(worker_task)
    print(f"[MAIN] Created {NUM_WORKERS} workers")

    # 스케줄러 태스크 생성
    scheduler_task = asyncio.create_task(task_scheduler(booking_urls, task_queue))
    print(f"[MAIN] Scheduler started")

    try:
        print(f"\n🚀 시스템 시작! (워커 풀 방식)\n")
        await asyncio.gather(scheduler_task, *worker_tasks)

    except KeyboardInterrupt:
        print("\n\n사용자에 의해 종료되었습니다.")
    except Exception as e:
        print(f"\n[ERROR] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n종료 중...")

        # 모든 워커에게 종료 신호 전송
        for _ in range(NUM_WORKERS):
            await task_queue.put((None, None, None))

        # 스케줄러 취소
        scheduler_task.cancel()

        # 모든 워커 태스크 종료 대기
        for task in worker_tasks:
            task.cancel()

        await asyncio.gather(scheduler_task, *worker_tasks, return_exceptions=True)

        # 브라우저 정리
        if browser_context:
            await browser_context.close()
            browser_context = None
        if playwright_instance:
            await playwright_instance.stop()
            playwright_instance = None

        # 탭 풀 정리
        for worker_id in list(tab_pools.keys()):
            for tab in list(tab_pools[worker_id].values()):
                try:
                    await tab.close()
                except:
                    pass
        tab_pools.clear()
        tab_last_used.clear()
        tab_usage_counts.clear()

        # 로깅 워커 종료
        stop_logging_worker()
        print("[MAIN] Logging worker stopped")

        print("종료 완료!")


if __name__ == "__main__":
    print("네이버 예약 자동 모니터링 + GraphQL API 시스템")
    print("=" * 60)
    asyncio.run(main())
