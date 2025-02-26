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

from telegram_message import send_telegram_notification
from urls import urls
from util import get_hash
from valid_check import is_content_valid

user_data_dir = r"C:\Users\Narang\AppData\Local\Google\Chrome\User Data"
profile_dir = r"Default"
chrome_path = r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe"
# driver_path = r"D:\save\Programs\executable\chromedriver\chromedriver.exe"
driver_path=r"D:\save\Programs\executable\chromedriver\135.0.7023\chromedriver.exe"
current_hash = ""
# https://www.chromedriverdownload.com/en/downloads/chromedriver-130-download

def create_browser():
    options = Options()
    options.add_argument("--disable-setuid-sandbox")

    service = Service(executable_path=driver_path)
    options.add_argument(f"--user-data-dir={user_data_dir}")  # Path to the user data directory
    options.add_argument(f"--profile-directory={profile_dir}")  # Profile directory
    # options.add_argument("--single-process")
    # options.add_argument("--disable-gpu")
    # options.add_argument("--no-sandbox")
    options.add_argument(f"--remote-debugging-port=9354")  # Add this line
    # options.add_argument("--disable-software-rasterizer")  # Add this line
    options.binary_location = chrome_path
    driver = webdriver.Chrome(service = service, options=options)
    return driver


def extract_date_from_url(url):
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    start_date_time = query_params.get('startDateTime')
    start_date = query_params.get('startDate')
    if start_date_time:
        return start_date_time[0]
    elif start_date:
        return start_date[0]
    else:
        return None


def calculate_interval(start_date_str):
    if start_date_str is None:
        #아마도 에러
        asyncio.run(send_telegram_notification(f"[Note] Error detected! {start_date_str}", "","err"))
        return None
    if start_date_str.find("T") > 0:
        start_datetime = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%S%z")
    else:
        start_datetime = datetime.strptime(start_date_str + "T00:00:00+0900", "%Y-%m-%dT%H:%M:%S%z")
    now = datetime.now(start_datetime.tzinfo)
    delta = start_datetime - now
    if delta.total_seconds() < 0:  # 이게 오늘
        return random.uniform(2, 7)
    if delta.days > 7:
        return random.uniform(200, 300)
    if delta.days > 1:
        return random.uniform(20, 50)
    return random.uniform(3, 10)  # 내일


def perform_task(driver, url, tag, index, current_hash, current_data, validate_level=2):
    print(f"[{tag}] perform_task at: {time.ctime()}")
    driver, new_hash, new_content = get_hash(driver, url, create_browser)
    if new_hash is None:
        print("fatal error to get hash!")
        return current_hash
    validate_level_max = 2
    try:
        validate_level_max = int(validate_level)
        print(f"[{tag}] validate to {validate_level_max}")
    except:
        print(f"[{tag}] validate to {validate_level_max}")
    ret = None
    if new_hash != current_hash:
        if int(validate_level_max) > 0:
            ret = is_content_valid(new_content, validate_level_max)
            if ret is None:
                print(f"[{tag}] Detected the inactive page message2, not sending update.")
            else:
                if len(ret) > 0:
                    if current_data == ret:
                        print(f"[{tag}] same with prev")
                    else:
                        message = f"[{tag}] Change detected with ret {ret} at: {time.ctime()}"
                        asyncio.run(send_telegram_notification(message))
                        print(f"[{tag}] Change detected at:", time.ctime())
                        print(f"[{tag}] rtn_contents {ret}")
                else:
                    if validate_level_max == 1:
                        message = f"[{tag}] Change detected! {ret} at: {time.ctime()}"
                        asyncio.run(send_telegram_notification(message))
    else:
        print(f"[{tag}] Detected same page")
    return new_hash, ret


def worker(task_queue):
    driver = create_browser()
    while True:
        url, tag, index, current_hash, current_data, validate_level, work_cnt = task_queue.get()
        if url is None:
            break
        if work_cnt == 0:
            asyncio.run(send_telegram_notification(f"work add for tag:{tag}, index:{index}"))
        print(f"pop task : {tag} work_cnt {work_cnt}")
        new_hash, new_data = perform_task(driver, url, tag, index, current_hash, current_data, validate_level)
        task_queue.task_done()
        # 작업 완료 후 다시 큐에 추가
        task_queue.put((url, tag, index, new_hash, new_data, validate_level, work_cnt + 1))



def improved_task_scheduler(urls, task_queue):
    next_run_times = []
    for index, item in enumerate(urls, start=1):
        date = extract_date_from_url(item["url"])
        interval = calculate_interval(date)
        next_run = time.time() + interval
        heapq.heappush(next_run_times, (next_run, index - 1))  # index - 1 to match list indexing

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
            if interval:
                next_run = now + interval
            else:
                next_run=now+random.uniform(2, 7)
            heapq.heappush(next_run_times, (next_run, url_index))

            print(f"Scheduled task for {item['tag']} with interval {interval:.2f} seconds.")
        else:
            # Sleep for a short time if no tasks are ready
            time.sleep(0.1)


# 단일 워커 스레드 생성 및 시작
task_queue = Queue()

worker_thread = threading.Thread(target=worker, args=(task_queue,))
worker_thread.start()

# Task Scheduler 스레드 생성 및 시작
scheduler_thread = threading.Thread(target=improved_task_scheduler, args=(urls, task_queue))
scheduler_thread.start()

# 메인 스레드는 계속 대기
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    # 종료 신호 보내기
    task_queue.put((None, None, None, None, None, None, None))
    worker_thread.join()
    scheduler_thread.join()
