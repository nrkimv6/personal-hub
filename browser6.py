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

from run import send_telegram_sync, perform_task, calculate_interval, extract_date_from_url, loop, create_browser
from telegram_message import send_telegram_notification
from urls import urls
from util import get_hash
from valid_check import is_content_valid

def worker(task_queue):
    driver = create_browser()
    while True:
        url, tag, index, current_hash, current_data, validate_level, work_cnt = task_queue.get()
        if url is None:
            break
        if work_cnt == 0:
            send_telegram_sync(f"work add for tag:{tag}, index:{index}")
        print(f"pop task : {tag} work_cnt {work_cnt}")
        new_hash, new_data = perform_task(driver, url, tag, index, current_hash, current_data, validate_level)
        task_queue.task_done()
        # 작업 완료 후 큐에 다시 추가하지 않음

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

            # Add task to queue
            task_queue.put((item["url"], item["tag"], url_index + 1, None, None, item.get("validate"), 1))

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
    for _ in range(num_workers):
        worker_thread = threading.Thread(target=worker, args=(task_queue,))
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