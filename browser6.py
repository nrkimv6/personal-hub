import random
import threading
import heapq
import time
from datetime import datetime, timedelta
from queue import Queue
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import asyncio
from functools import partial

from run_selenium import create_browser, loop, perform_task, calculate_interval, extract_date_from_url
from telegram_message import send_telegram_notification
from urls import urls
from util import get_hash
from valid_check import is_content_valid

# URL별 상태를 저장하는 전역 딕셔너리
url_states = {}

def worker(task_queue, worker_id):
    driver = create_browser()
    while True:
        url, tag, index, current_hash, current_data, validate_level, work_cnt = task_queue.get()
        if url is None:
            break
        if work_cnt == 0:
            send_telegram_sync(f"Worker {worker_id}: work add for tag:{tag}, index:{index}")
        print(f"Worker {worker_id}: pop task : {tag} work_cnt {work_cnt}")
        
        # URL 상태 가져오기
        if url not in url_states:
            url_states[url] = {"hash": current_hash, "data": current_data}
        else:
            current_hash = url_states[url]["hash"]
            current_data = url_states[url]["data"]
        
        new_hash, new_data = perform_task(driver, url, tag, index, current_hash, current_data, validate_level)
        
        # URL 상태 업데이트
        if new_hash is not None:
            url_states[url] = {"hash": new_hash, "data": new_data}
        
        task_queue.task_done()

def improved_task_scheduler(urls, task_queue):
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
            task_queue.put((
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
            time.sleep(0.1)


def send_telegram_sync(message):
    try:
        future = asyncio.run_coroutine_threadsafe(
            send_telegram_notification(message),
            loop
        )
        return future.result(timeout=10)  # 10초 타임아웃 설정
    except Exception as e:
        print(f"텔레그램 발송 실패: {str(e)}")
        return None



# 메인 코드 부분 수정
if __name__ == "__main__":
    # 단일 워커 스레드 생성 및 시작
    task_queue = Queue()
    
    # 이벤트 루프를 별도 스레드에서 실행
    def run_event_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    
    loop_thread = threading.Thread(target=run_event_loop, daemon=True)
    loop_thread.start()
    
    # 여러 워커 스레드 생성
    num_workers = 3  # 워커 수 조정 가능
    worker_threads = []
    for i in range(num_workers):
        worker_thread = threading.Thread(target=worker, args=(task_queue, i+1))
        worker_thread.start()
        worker_threads.append(worker_thread)
    
    scheduler_thread = threading.Thread(target=improved_task_scheduler, args=(urls, task_queue))
    scheduler_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 모든 워커 스레드 종료
        for _ in range(num_workers):
            task_queue.put((None, None, None, None, None, None, None))
        
        loop.call_soon_threadsafe(loop.stop)
        for worker_thread in worker_threads:
            worker_thread.join()
        scheduler_thread.join()
        loop_thread.join() 