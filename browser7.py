import asyncio
import time
from playwright.async_api import async_playwright
import os
from pathlib import Path
import random
from datetime import datetime

from run_playwright import user_data_dir, perform_task, extract_date_from_url, calculate_interval

# Global dictionary to store URL states across workers
url_states = {}
import random
import threading
import heapq
import time
from datetime import datetime, timedelta
from queue import Queue
import asyncio
from functools import partial

from telegram_message import send_telegram_notification, send_desktop_notification
from urls import urls
from util import get_hash
from valid_check import is_content_valid

# URL별 상태를 저장하는 전역 딕셔너리
url_states = {}

# 단일 브라우저 컨텍스트와 playwright 인스턴스를 저장할 전역 변수
browser_context = None
playwright_instance = None

# 워커별 탭 풀을 저장할 전역 딕셔너리
tab_pools = {}
# 탭의 마지막 사용 시간을 저장할 전역 딕셔너리
tab_last_used = {}

# 탭 풀 설정
MAX_TABS_PER_WORKER = 5
TAB_CLEANUP_THRESHOLD = 300  # 5분 이상 사용되지 않은 탭 정리

async def cleanup_old_tabs(worker_id):
    """오래된 탭을 정리합니다."""
    current_time = time.time()
    tabs_to_remove = []
    
    for tab_id, last_used in tab_last_used.get(worker_id, {}).items():
        if current_time - last_used > TAB_CLEANUP_THRESHOLD:
            tabs_to_remove.append(tab_id)
    
    for tab_id in tabs_to_remove:
        if tab_id in tab_pools.get(worker_id, {}):
            await tab_pools[worker_id][tab_id].close()
            del tab_pools[worker_id][tab_id]
            del tab_last_used[worker_id][tab_id]

async def get_tab(worker_id):
    """사용 가능한 탭을 가져오거나 새로 생성합니다."""
    global browser_context
    
    # 오래된 탭 정리
    await cleanup_old_tabs(worker_id)
    
    # 워커의 탭 풀이 없으면 초기화
    if worker_id not in tab_pools:
        tab_pools[worker_id] = {}
        tab_last_used[worker_id] = {}
    
    # 사용 가능한 탭 찾기 - 모든 탭을 사용 가능한 것으로 간주
    available_tabs = list(tab_pools[worker_id].keys())
    
    if available_tabs:
        # 사용 가능한 탭이 있으면 재사용
        tab_id = random.choice(available_tabs)
        tab = tab_pools[worker_id][tab_id]
    else:
        # 탭 수가 제한에 도달하지 않았으면 새로 생성
        if len(tab_pools[worker_id]) < MAX_TABS_PER_WORKER:
            tab = await browser_context.new_page()
            tab_id = str(len(tab_pools[worker_id]))
            tab_pools[worker_id][tab_id] = tab
        else:
            # 탭 수가 제한에 도달했으면 가장 오래된 탭 재사용
            tab_id = min(tab_last_used[worker_id].items(), key=lambda x: x[1])[0]
            tab = tab_pools[worker_id][tab_id]
    
    # 탭 사용 시간 업데이트
    tab_last_used[worker_id][tab_id] = time.time()
    
    return tab

async def initialize_browser():
    """단일 브라우저 컨텍스트를 초기화합니다."""
    global browser_context, playwright_instance
    
    if browser_context is None:
        # Windows 환경의 Chrome 프로필 디렉토리 설정
        profile_dir = Path(os.environ['LOCALAPPDATA']) / "Google" / "Chrome" / "User Data"
        worker_profile_dir = profile_dir / "Default"
        
        # 프로필 디렉토리가 없으면 생성
        if not worker_profile_dir.exists():
            print("프로필 디렉토리가 없습니다. 새로 생성합니다.")
            worker_profile_dir.mkdir(parents=True, exist_ok=True)
        
        # Playwright 인스턴스 생성 및 저장
        playwright_instance = await async_playwright().start()
        
        # 브라우저 컨텍스트 생성 및 저장
        browser_context = await playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(worker_profile_dir),
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        print("브라우저 컨텍스트가 초기화되었습니다.")
    
    return browser_context

async def worker_task(url, tag, index, current_hash, current_data, validate_level, work_cnt, worker_id):
    """Individual worker task that processes a single URL check"""
    if work_cnt == 0:
        await send_telegram_notification(f"Worker {worker_id}: work add for tag:{tag}, index:{index}")
    print(f"Worker {worker_id}: processing task : {tag} work_cnt {work_cnt}")

    # Get URL state from global dictionary
    if url not in url_states:
        url_states[url] = {"hash": current_hash, "data": current_data}
    else:
        current_hash = url_states[url]["hash"]
        current_data = url_states[url]["data"]

    try:
        # Get or create tab
        tab = await get_tab(worker_id)
        
        new_hash, new_data = await perform_task(tab, url, tag, current_hash, current_data,
                                                validate_level)

        # Update URL state
        if new_hash is not None:
            url_states[url] = {"hash": new_hash, "data": new_data}

    except Exception as e:
        print(f"Error in worker_task: {e}")
        # 탭 풀 초기화
        if worker_id in tab_pools:
            for tab in tab_pools[worker_id].values():
                try:
                    await tab.close()
                except:
                    pass
            tab_pools[worker_id] = {}
            tab_last_used[worker_id] = {}

    return tag, index


async def worker(task_queue, worker_id):
    """Worker that continually processes tasks from the queue"""
    while True:
        try:
            # Get a task from the queue
            task = await task_queue.get()
            url, tag, index, current_hash, current_data, validate_level, work_cnt = task

            if url is None:  # Sentinel value to stop the worker
                print(f"Worker {worker_id}: Shutting down")
                task_queue.task_done()
                break

            # Process the task
            await worker_task(url, tag, index, current_hash, current_data, validate_level, work_cnt, worker_id)

            # Mark the task as done
            task_queue.task_done()

        except Exception as e:
            print(f"Worker {worker_id} encountered an error: {e}")
            # Still mark task as done even if it failed
            if 'task_queue' in locals() and 'task' in locals():
                task_queue.task_done()

            # Brief pause before trying next task
            await asyncio.sleep(1)


async def improved_task_scheduler(urls, task_queue):
    next_run_times = []
    for index, item in enumerate(urls, start=1):
        date = extract_date_from_url(item["url"])
        interval = calculate_interval(date)
        if interval is None:
            interval = random.uniform(2, 7)
        next_run = time.time() + interval
        heapq.heappush(next_run_times, (next_run, index - 1))

    while True:
        now = time.time()
        if next_run_times and next_run_times[0][0] <= now:
            _, url_index = heapq.heappop(next_run_times)
            item = urls[url_index]

            # URL 상태 가져오기
            current_state = url_states.get(item["url"], {"hash": None, "data": None})

            # Add task to queue with current state
            await task_queue.put((
                item["url"],
                item["tag"],
                url_index + 1,
                current_state["hash"],
                current_state["data"],
                item.get("validate"),
                1
            ))

            # Calculate next run time and add back to heap
            date = extract_date_from_url(item["url"])
            interval = calculate_interval(date)
            if interval is None:
                interval = random.uniform(2, 7)
            next_run = now + interval
            heapq.heappush(next_run_times, (next_run, url_index))

            print(f"Scheduled task for {item['tag']} with interval {interval:.2f} seconds.")
        else:
            # Sleep for a short time if no tasks are ready
            await asyncio.sleep(0.1)


def send_telegram_sync(message):
    try:
        # 현재 스레드의 이벤트 루프를 가져옵니다
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 이미 실행 중인 이벤트 루프가 있는 경우
            future = asyncio.run_coroutine_threadsafe(
                send_telegram_notification(message),
                loop
            )
            return future.result(timeout=10)  # 10초 타임아웃 설정
        else:
            # 이벤트 루프가 실행 중이 아닌 경우 새로 생성
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(send_telegram_notification(message))
            finally:
                loop.close()
    except Exception as e:
        print(f"텔레그램 발송 실패: {str(e)}")
        return None


# 메인 코드 부분 수정
async def main():
    # 워커 수 설정
    num_workers = 3  # 워커 수 조정 가능
    
    # 프로그램 시작 알림
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notification_message = (
        f"웹 페이지 모니터링 시스템이 시작되었습니다.\n"
        f"시작 시간: {start_time}\n"
        f"모니터링 대상 URL 수: {len(urls)}\n"
        f"워커 수: {num_workers}\n"
        f"탭 수 제한: {MAX_TABS_PER_WORKER}개/워커"
    )
    send_desktop_notification("모니터링 시스템 시작", notification_message)
    
    # 브라우저 초기화
    await initialize_browser()
    
    # 단일 워커 스레드 생성 및 시작
    task_queue = asyncio.Queue()

    # 여러 워커 태스크 생성
    worker_tasks = []
    for i in range(num_workers):
        worker_task = asyncio.create_task(worker(task_queue, i + 1))
        worker_tasks.append(worker_task)

    # 스케줄러 태스크 생성
    scheduler_task = asyncio.create_task(improved_task_scheduler(urls, task_queue))

    try:
        # 모든 태스크가 완료될 때까지 대기
        await asyncio.gather(scheduler_task, *worker_tasks)
    except KeyboardInterrupt:
        # 프로그램 종료 알림
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        notification_message = (
            f"웹 페이지 모니터링 시스템이 종료되었습니다.\n"
            f"종료 시간: {end_time}\n"
            f"실행 시간: {datetime.now() - datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')}"
        )
        send_desktop_notification("모니터링 시스템 종료", notification_message)
        
        # 모든 워커 태스크 종료
        for _ in range(num_workers):
            await task_queue.put((None, None, None, None, None, None, None))
        
        # 모든 태스크 정리
        for task in worker_tasks:
            task.cancel()
        scheduler_task.cancel()
        
        # 브라우저 컨텍스트와 playwright 인스턴스 정리
        global browser_context, playwright_instance
        if browser_context:
            await browser_context.close()
            browser_context = None
        if playwright_instance:
            await playwright_instance.stop()
            playwright_instance = None
        
        # 탭 풀 정리
        for worker_id in tab_pools:
            for tab in tab_pools[worker_id].values():
                try:
                    await tab.close()
                except:
                    pass
        
        # 남은 태스크들이 정리될 때까지 대기
        await asyncio.gather(*worker_tasks, scheduler_task, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())