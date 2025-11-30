"""
네이버 예약 자동 모니터링 + 자동 예약 통합 시스템

browser7.py의 모니터링 기능과 auto_book.py의 예약 기능을 통합하여
예약 가능 슬롯을 감지하면 자동으로 예약을 실행합니다.
"""

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

# 공통 유틸리티 임포트
from old.browser_utils import (
    initialize_browser,
    normalize_booking_url,
    wait_for_button_enabled,
    check_time_slots
)

# browser7.py에서 필요한 함수들 임포트
sys.path.insert(0, str(Path(__file__).parent / "old"))

# browser7 임포트 시 경로 문제 해결
import importlib.util
browser7_path = Path(__file__).parent / "old" / "browser7.py"
spec = importlib.util.spec_from_file_location("browser7", browser7_path)
browser7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser7)

perform_task_with_fetch = browser7.perform_task_with_fetch
is_data_time_in_range = browser7.is_data_time_in_range
KST = browser7.KST

# url_book.py에서 예약 URL 목록 임포트
from old.url_book import booking_urls

# 설정
user_data_dir = os.path.join(os.path.dirname(__file__), "browser_data")
profile_dir = "AutoBooking"

# 자동 예약 설정
ENABLE_AUTO_BOOKING = True  # False로 설정하면 알림만 발송
DRY_RUN_MODE = False  # True면 실제 예약 버튼을 클릭하지 않음 (테스트용)

# 탭 관리 설정 (browser7.py와 동일)
MAX_TABS_PER_WORKER = 5  # 워커당 최대 탭 수
MAX_USES_PER_TAB = 50  # 탭당 최대 사용 횟수 (메모리 관리)
TAB_CLEANUP_THRESHOLD = 600  # 10분 이상 미사용 탭 정리

# 전역 탭 풀 (browser7.py와 동일한 구조)
tab_pools = {}  # 워커별 탭 딕셔너리
tab_last_used = {}  # 탭 마지막 사용 시간
tab_usage_counts = {}  # 탭 사용 횟수


async def cleanup_old_tabs(worker_id):
    """오래된 탭을 정리합니다 (browser7.py와 동일)"""
    current_time = time.time()
    tabs_to_remove = []

    if worker_id not in tab_last_used:
        return

    # 탭 수가 제한을 초과했는지 확인
    tab_count = len(tab_pools.get(worker_id, {}))
    print(f"[CLEANUP] Worker {worker_id} has {tab_count} tabs, MAX: {MAX_TABS_PER_WORKER}")

    if tab_count > MAX_TABS_PER_WORKER:
        print(f"[CLEANUP] Worker {worker_id} has too many tabs, checking for cleanup...")
        for tab_id, last_used in tab_last_used.get(worker_id, {}).items():
            time_since_last_use = current_time - last_used
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


async def get_tab(browser_context, worker_id):
    """사용 가능한 탭을 가져오거나 새로 생성합니다 (browser7.py와 동일)"""
    import uuid

    print(f"[GET_TAB] Worker {worker_id} requesting tab...")
    await cleanup_old_tabs(worker_id)

    if worker_id not in tab_pools:
        tab_pools[worker_id] = {}
        tab_last_used[worker_id] = {}
        tab_usage_counts[worker_id] = {}
        print(f"[GET_TAB] Initialized tab pools for worker {worker_id}")

    available_tabs = list(tab_pools[worker_id].keys())
    print(f"[GET_TAB] Worker {worker_id} has {len(available_tabs)} available tabs")

    # 사용 가능한 탭이 있으면 재사용
    if available_tabs:
        # 가장 오래된 탭 선택 (LRU)
        tab_id = min(tab_last_used[worker_id].items(), key=lambda x: x[1])[0]
        tab = tab_pools[worker_id][tab_id]
        print(f"[GET_TAB] Reusing existing tab {tab_id} for worker {worker_id}")

        # 탭이 살아있는지 확인
        try:
            _ = tab.url
        except Exception as e:
            print(f"[GET_TAB] Tab {tab_id} is dead ({e}), removing and creating new one...")
            del tab_pools[worker_id][tab_id]
            del tab_last_used[worker_id][tab_id]
            if tab_id in tab_usage_counts[worker_id]:
                del tab_usage_counts[worker_id][tab_id]
            # 새 탭 생성으로 진행
            tab = await browser_context.new_page()
            tab_id = str(uuid.uuid4())
            tab_pools[worker_id][tab_id] = tab
            tab_usage_counts[worker_id][tab_id] = 0
            tab_last_used[worker_id][tab_id] = time.time()
            print(f"[GET_TAB] Created replacement tab {tab_id} for worker {worker_id}")
    elif len(tab_pools[worker_id]) < MAX_TABS_PER_WORKER:
        # 새 탭 생성
        print(f"[GET_TAB] Creating new tab for worker {worker_id}")
        tab = await browser_context.new_page()
        tab_id = str(uuid.uuid4())
        tab_pools[worker_id][tab_id] = tab
        tab_usage_counts[worker_id][tab_id] = 0
        tab_last_used[worker_id][tab_id] = time.time()
        print(f"[GET_TAB] Created new tab {tab_id} for worker {worker_id}")
    else:
        # 제한에 도달했으면 가장 오래된 탭 재사용
        tab_id = min(tab_last_used[worker_id].items(), key=lambda x: x[1])[0]
        tab = tab_pools[worker_id][tab_id]
        print(f"[GET_TAB] Reusing oldest tab {tab_id} for worker {worker_id}")

    # 사용 횟수 체크 (메모리 관리)
    current_usage = tab_usage_counts[worker_id].get(tab_id, 0)
    if current_usage >= MAX_USES_PER_TAB:
        print(f"[GET_TAB] Tab {tab_id} reached max uses ({MAX_USES_PER_TAB}), replacing...")
        await tab.close()
        del tab_pools[worker_id][tab_id]
        del tab_last_used[worker_id][tab_id]
        del tab_usage_counts[worker_id][tab_id]

        # 새 탭 생성
        tab = await browser_context.new_page()
        tab_id = str(uuid.uuid4())
        tab_pools[worker_id][tab_id] = tab
        tab_usage_counts[worker_id][tab_id] = 0
        tab_last_used[worker_id][tab_id] = time.time()
        print(f"[GET_TAB] Created replacement tab {tab_id} after max uses")

    return tab, tab_id


async def perform_booking(page, url, tag, available_slots):
    """
    예약 프로세스를 실행합니다.

    올바른 플로우:
    1. 상품 상세 페이지 접속 (startDateTime 파라미터 포함)
    2. 시간 선택
    3. "다음" 버튼 클릭 → /request 페이지로 이동
    4. 필수 항목 선택 & 동의
    5. 예매 버튼 클릭

    Args:
        page: Playwright 페이지 객체
        url: 예약 URL (상품 상세 페이지)
        tag: 예약 태그 (로그용)
        available_slots: 예약 가능한 슬롯 리스트

    Returns:
        bool: 예약 성공 여부
    """
    print(f"\n[BOOKING] {tag} 예약 시작")

    # 첫 번째 예약 가능 슬롯에서 시간 추출
    if not available_slots:
        print("[BOOKING] 예약 가능한 슬롯이 없습니다.")
        return False

    # 슬롯 형식: "2025-12-02 21:00:00 (2매) [부분모호:...]"
    first_slot = str(available_slots[0])
    import re
    time_match = re.search(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}):(\d{2})', first_slot)
    if not time_match:
        print(f"[BOOKING] 슬롯에서 시간을 추출할 수 없습니다: {first_slot}")
        return False

    slot_date = time_match.group(1)  # 2025-12-02
    slot_hour = time_match.group(2)  # 21
    slot_minute = time_match.group(3)  # 00

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

    print(f"[BOOKING] 예약할 시간: {slot_date} {display_time}")

    # URL에서 비즈니스 파라미터 추출
    url_pattern = r'booking/(\d+)/bizes/(\d+)/items/(\d+)'
    url_match = re.search(url_pattern, url)
    if not url_match:
        print(f"[BOOKING] URL에서 비즈니스 정보를 추출할 수 없습니다: {url}")
        return False

    category = url_match.group(1)
    business_id = url_match.group(2)
    item_id = url_match.group(3)

    # 상품 상세 페이지 URL 구성 (startDateTime 파라미터 포함)
    from urllib.parse import quote
    start_datetime = f"{slot_date}T00:00:00+09:00"
    start_datetime_encoded = quote(start_datetime, safe='')
    detail_url = f"https://booking.naver.com/booking/{category}/bizes/{business_id}/items/{item_id}?startDateTime={start_datetime_encoded}"

    print(f"[BOOKING] 상품 상세 페이지 URL: {detail_url}")

    try:
        # STEP 1: 상품 상세 페이지 접속
        print("[STEP 1] 상품 상세 페이지 로딩 중...")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)  # 페이지 로드 대기

        # STEP 2: 날짜 확인 (URL에 포함되어 있으므로 자동 선택되어야 함)
        print("[STEP 2] 날짜 선택 확인 중...")
        try:
            selected_date = await page.wait_for_selector('button.calendar_date.selected', timeout=5000)
            if selected_date:
                date_text = await selected_date.inner_text()
                print(f"[STEP 2] ✓ 선택된 날짜: {date_text}")
        except Exception as e:
            print(f"[STEP 2] 경고: 날짜 선택 확인 실패 ({e})")

        # STEP 3: 시간 선택
        print(f"[STEP 3] 시간 선택 중... (목표: {display_time})")
        try:
            # 시간 버튼 찾기 (텍스트로 매칭)
            time_buttons = await page.query_selector_all('button.btn_time')
            time_selected = False

            for btn in time_buttons:
                btn_text = await btn.inner_text()
                if display_time in btn_text:
                    await btn.click()
                    print(f"[STEP 3] ✓ 시간 선택 완료: {btn_text}")
                    time_selected = True
                    await page.wait_for_timeout(500)
                    break

            if not time_selected:
                print(f"[STEP 3] ⚠️ 목표 시간({display_time})을 찾을 수 없습니다.")
                # 사용 가능한 시간 목록 출력
                available_times_list = []
                for btn in time_buttons:
                    btn_text = await btn.inner_text()
                    available_times_list.append(btn_text)
                print(f"[STEP 3] 사용 가능한 시간: {', '.join(available_times_list)}")
                return False

        except Exception as e:
            print(f"[STEP 3] 시간 선택 실패: {e}")
            return False

        # STEP 4: "다음" 버튼 클릭 → /request 페이지로 이동
        print("[STEP 4] '다음' 버튼 클릭 중...")
        try:
            # "다음" 버튼 찾기 (여러 가능한 선택자 시도)
            next_button_selectors = [
                'button.NextButton__btn_next__kfLFW',  # 분석 결과에서 발견된 선택자
                'button:has-text("다음")',
                'button.btn_next',
                'button[class*="btn_next"]'
            ]

            next_button = None
            for selector in next_button_selectors:
                try:
                    next_button = await page.wait_for_selector(selector, timeout=3000)
                    if next_button:
                        print(f"[STEP 4] ✓ '다음' 버튼 찾음 (선택자: {selector})")
                        break
                except:
                    continue

            if not next_button:
                print("[STEP 4] ⚠️ '다음' 버튼을 찾을 수 없습니다.")
                return False

            # 버튼 클릭
            await next_button.click()
            print("[STEP 4] ✓ '다음' 버튼 클릭 완료")

            # /request 페이지로 이동 대기
            await page.wait_for_url('**/request**', timeout=10000)
            print("[STEP 4] ✓ 예매 확인 페이지(/request)로 이동 완료")
            await page.wait_for_timeout(2000)

        except Exception as e:
            print(f"[STEP 4] '다음' 버튼 클릭 실패: {e}")
            return False

        # STEP 5: 인원 선택 확인 (필요한 경우)
        print("[STEP 5] 인원 선택 확인 중...")
        try:
            person_button = await page.query_selector('button.select_btn')
            if person_button:
                person_text = await person_button.inner_text()
                print(f"[STEP 5] ✓ 현재 인원: {person_text}")
        except Exception as e:
            print(f"[STEP 5] 인원 확인 실패 (계속 진행): {e}")

        # STEP 6: 예매 버튼 활성화 대기
        print("[STEP 6] 예매 버튼 활성화 대기 중...")
        is_enabled = await wait_for_button_enabled(page, timeout=10000)

        if not is_enabled:
            print("[STEP 6] ⚠️ 예매 버튼이 활성화되지 않았습니다.")
            return False

        print("[STEP 6] ✓ 예매 버튼 활성화됨!")

        # STEP 7: 예매 버튼 클릭
        print("[STEP 7] 예매 버튼 클릭 준비...")

        if DRY_RUN_MODE:
            print("⚠️  [DRY RUN MODE] 실제 예매를 진행하지 않습니다 (테스트 모드)")
            print("실제 예매를 진행하려면 DRY_RUN_MODE = False로 설정하세요!")
        else:
            # 실제 예매 실행
            await page.click('button.btn_request')
            print("[STEP 7] ✅ 예매 버튼 클릭 완료!")
            await page.wait_for_timeout(3000)  # 3초 대기

        print("[SUCCESS] 예약 프로세스 완료!")
        return True

    except Exception as e:
        print(f"[ERROR] 예약 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


async def monitor_and_book_worker(browser_context, url_info, worker_id):
    """
    단일 URL에 대한 모니터링 및 자동 예약 워커

    Args:
        browser_context: 브라우저 컨텍스트
        url_info: URL 정보 딕셔너리
        worker_id: 워커 ID
    """
    url = url_info["url"]
    tag = url_info["tag"]
    description = url_info.get("description", "")
    time_range = url_info.get("time_range")  # 시간 범위 필터 (옵션)

    print(f"\n[WORKER {worker_id}] {tag} 모니터링 시작")
    print(f"[WORKER {worker_id}] URL: {url}")
    print(f"[WORKER {worker_id}] 설명: {description}")
    if time_range:
        print(f"[WORKER {worker_id}] 시간 범위: {time_range}")

    # 모니터링 상태
    current_hash = None
    current_data = []
    last_check_time = datetime.now(KST)
    last_notified_hash = None

    check_count = 0

    try:
        while True:
            check_count += 1
            check_time = datetime.now(KST)

            print(f"\n[WORKER {worker_id}] [{tag}] 확인 #{check_count} - {check_time.strftime('%H:%M:%S')}")

            # 탭 풀에서 탭 가져오기 (browser7.py와 동일)
            tab, tab_id = await get_tab(browser_context, worker_id)

            try:
                # Fetch API로 예약 가능 여부 확인
                # perform_task_with_fetch가 내부적으로 첫 페이지 로드를 처리함
                new_hash, new_data = await perform_task_with_fetch(
                    tab, url, tag, current_hash, current_data,
                    validate_level=2, last_check_time=last_check_time
                )

                # 데이터 해시 계산
                import hashlib
                if new_data:
                    data_hash = hashlib.md5(str(new_data).encode('utf-8')).hexdigest()
                else:
                    data_hash = hashlib.md5(b'').hexdigest()

                # 변경 감지 및 알림
                if data_hash != last_notified_hash:
                    # 예약 가능 슬롯이 있는 경우
                    if new_data and len(new_data) > 0:
                        print(f"[WORKER {worker_id}] [{tag}] ✅ 예약 가능 감지!")
                        print(f"[WORKER {worker_id}] [{tag}] 슬롯: {new_data}")

                        # 시간 범위 필터링 (설정된 경우)
                        if time_range:
                            print(f"[WORKER {worker_id}] [{tag}] 시간 범위 체크: {time_range}")
                            in_range = is_data_time_in_range(new_data, time_range)
                        else:
                            in_range = True  # 시간 범위 필터가 없으면 항상 True

                        if in_range:
                            # 텔레그램 알림 발송
                            from old.telegram_message import send_telegram_notification
                            message = f"🎯 [{tag}] 예약 가능!\n\n"
                            message += f"슬롯: {', '.join(str(slot) for slot in new_data)}\n"
                            if time_range:
                                message += f"시간 범위: {time_range}\n"
                            message += f"URL: {url}\n\n"

                            if ENABLE_AUTO_BOOKING:
                                message += "🤖 자동 예약을 시도합니다..."
                                await send_telegram_notification(message)

                                # ⚠️ 예약 시작: 탭을 독점하고 모니터링 중단
                                print(f"[WORKER {worker_id}] [{tag}] 🔒 탭 독점 모드 - 예약 완료까지 모니터링 중단")

                                # 자동 예약 실행 (전용 탭 사용)
                                print(f"[WORKER {worker_id}] [{tag}] 🤖 자동 예약 시작...")
                                booking_success = await perform_booking(tab, url, tag, new_data)

                                if booking_success:
                                    success_msg = f"✅ [{tag}] 자동 예약 {'시뮬레이션' if DRY_RUN_MODE else ''} 완료!"
                                    print(f"[WORKER {worker_id}] {success_msg}")
                                    await send_telegram_notification(success_msg)
                                else:
                                    fail_msg = f"❌ [{tag}] 자동 예약 실패"
                                    print(f"[WORKER {worker_id}] {fail_msg}")
                                    await send_telegram_notification(fail_msg)

                                # 예약 종료 후 탭 복구
                                print(f"[WORKER {worker_id}] [{tag}] 🔓 탭 독점 해제 - 모니터링 재개 준비")
                                # 탭을 닫고 풀에서 제거하여 다음 루프에서 새 탭 생성
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
                                print(f"[WORKER {worker_id}] [{tag}] 🆕 탭 교체 완료 - 다음 확인부터 새 탭 사용")
                            else:
                                message += "ℹ️ 자동 예약이 비활성화되어 있습니다."
                                await send_telegram_notification(message)

                            # 해시 업데이트
                            last_notified_hash = data_hash
                        else:
                            print(f"[WORKER {worker_id}] [{tag}] ⏭️  시간 범위 밖 슬롯, 알림 건너뜀")

                    # 예약 가능 슬롯이 없어진 경우
                    elif last_notified_hash is not None:
                        print(f"[WORKER {worker_id}] [{tag}] ℹ️  예약 마감")
                        last_notified_hash = data_hash

                # 상태 업데이트
                current_hash = new_hash
                current_data = new_data
                last_check_time = check_time

            except Exception as task_error:
                # Task Error: 에러 타입에 따라 탭 처리 결정 (browser7.py와 동일)
                error_msg = str(task_error)
                print(f"[WORKER {worker_id}] [{tag}] Task error: {error_msg}")

                # 심각한 오류인 경우만 탭 교체 (브라우저 관련 오류)
                serious_errors = [
                    "Browser is not connected",
                    "Target page, context or browser has been closed",
                    "Protocol error",
                    "Connection lost"
                ]

                is_serious_error = any(error in error_msg for error in serious_errors)

                if is_serious_error:
                    print(f"[WORKER {worker_id}] Serious browser error detected. Replacing tab {tab_id}.")
                    if tab:
                        try:
                            await tab.close()
                        except:
                            pass
                    # 탭 풀에서 제거
                    if worker_id in tab_pools and tab_id in tab_pools[worker_id]:
                        del tab_pools[worker_id][tab_id]
                    if worker_id in tab_last_used and tab_id in tab_last_used[worker_id]:
                        del tab_last_used[worker_id][tab_id]
                    if worker_id in tab_usage_counts and tab_id in tab_usage_counts[worker_id]:
                        del tab_usage_counts[worker_id][tab_id]
                else:
                    print(f"[WORKER {worker_id}] Minor error (data processing). Keeping tab {tab_id} for reuse.")
                    # 데이터 처리 오류는 탭을 보존 (탭 재사용 최적화)

            # 탭 사용 통계 업데이트 (성공/실패 관계없이) - browser7.py와 동일
            # 단, 탭이 풀에 존재하는 경우만 (예약으로 인해 탭이 제거된 경우 스킵)
            if worker_id in tab_pools and tab_id in tab_pools[worker_id]:
                if worker_id not in tab_last_used:
                    tab_last_used[worker_id] = {}
                if worker_id not in tab_usage_counts:
                    tab_usage_counts[worker_id] = {}

                tab_last_used[worker_id][tab_id] = time.time()
                current_usage = tab_usage_counts[worker_id].get(tab_id, 0) + 1
                tab_usage_counts[worker_id][tab_id] = current_usage
                print(f"[WORKER {worker_id}] Tab {tab_id} used {current_usage} times.")

                # 탭 사용 횟수 제한에 도달하면 교체 (메모리 관리)
                if current_usage >= MAX_USES_PER_TAB:
                    print(f"[WORKER {worker_id}] Tab {tab_id} reached max uses ({MAX_USES_PER_TAB}). Replacing for memory management.")
                    if tab:
                        try:
                            await tab.close()
                        except:
                            pass
                    # 탭 풀에서 제거
                    if worker_id in tab_pools and tab_id in tab_pools[worker_id]:
                        del tab_pools[worker_id][tab_id]
                    if worker_id in tab_last_used and tab_id in tab_last_used[worker_id]:
                        del tab_last_used[worker_id][tab_id]
                    if worker_id in tab_usage_counts and tab_id in tab_usage_counts[worker_id]:
                        del tab_usage_counts[worker_id][tab_id]
            else:
                print(f"[WORKER {worker_id}] Tab {tab_id} was removed (booking completed), skipping statistics update.")

            # 다음 확인까지 대기 (간격 조정 가능)
            await asyncio.sleep(5)  # 5초마다 확인

    except asyncio.CancelledError:
        print(f"\n[WORKER {worker_id}] [{tag}] 모니터링 중지됨")
    except Exception as e:
        print(f"\n[WORKER {worker_id}] [{tag}] 워커 오류 발생: {e}")


async def reinitialize_browser():
    """브라우저 컨텍스트를 재초기화합니다 (browser7.py 로직과 동일)"""
    global browser_context, playwright_instance

    # 기존 브라우저가 있다면 정리
    if browser_context is not None:
        try:
            print("[REINIT] 기존 브라우저 컨텍스트 종료 중...")
            await browser_context.close()
        except Exception as e:
            print(f"[REINIT] 브라우저 종료 오류: {e}")
        finally:
            browser_context = None

    if playwright_instance is not None:
        try:
            print("[REINIT] 기존 Playwright 인스턴스 정지 중...")
            await playwright_instance.stop()
        except Exception as e:
            print(f"[REINIT] Playwright 정지 오류: {e}")
        finally:
            playwright_instance = None

    # 새 브라우저 생성
    print("[REINIT] 새 브라우저 컨텍스트 생성 중...")
    browser_context, playwright_instance = await initialize_browser(
        user_data_dir=user_data_dir,
        profile_dir=profile_dir,
        headless=False
    )
    print("[REINIT] 브라우저 컨텍스트 재초기화 완료")
    return browser_context


async def main():
    """메인 실행 함수"""
    global browser_context, playwright_instance

    print("=" * 60)
    print("네이버 예약 자동 모니터링 + 자동 예약 시스템")
    print("=" * 60)
    print(f"시작 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모니터링 URL 수: {len(booking_urls)}")
    print(f"자동 예약: {'활성화' if ENABLE_AUTO_BOOKING else '비활성화'}")
    print(f"실행 모드: {'DRY RUN (시뮬레이션)' if DRY_RUN_MODE else 'LIVE (실제 예약)'}")
    print("=" * 60)
    print()

    # 브라우저 초기화
    browser_context, playwright_instance = await initialize_browser(
        user_data_dir=user_data_dir,
        profile_dir=profile_dir,
        headless=False  # 브라우저 창 표시 (디버깅용)
    )

    # 모든 URL에 대해 워커 생성
    workers = []
    for idx, url_info in enumerate(booking_urls, 1):
        worker = asyncio.create_task(
            monitor_and_book_worker(browser_context, url_info, idx)
        )
        workers.append(worker)

    try:
        # 모든 워커 실행
        print(f"\n🚀 {len(workers)}개 워커 시작!\n")
        await asyncio.gather(*workers)

    except KeyboardInterrupt:
        print("\n\n사용자에 의해 종료되었습니다.")
    except Exception as e:
        print(f"\n[ERROR] 예상치 못한 오류: {e}")
    finally:
        # 정리
        print("\n종료 중...")

        # 모든 워커 취소
        for worker in workers:
            worker.cancel()

        # 워커 종료 대기
        await asyncio.gather(*workers, return_exceptions=True)

        # 브라우저 정리
        if browser_context:
            await browser_context.close()
        if playwright_instance:
            await playwright_instance.stop()

        print("종료 완료!")


if __name__ == "__main__":
    print("네이버 예약 자동 모니터링 + 자동 예약 시스템")
    print("=" * 60)
    asyncio.run(main())
