import random
import threading
import heapq
import time
from datetime import datetime, timedelta
from queue import Queue

from plyer import notification
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from setting import user_data_dir, profile_dir, chrome_path, driver_path
import asyncio
from functools import partial

from telegram_message import send_telegram_notification
from urls import urls
from util import get_hash
from valid_check import is_content_valid


current_hash = ""
# https://www.chromedriverdownload.com/en/downloads/chromedriver-130-download

# 파일 최상단에 전역 이벤트 루프 생성
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


# send_telegram_notification을 동기적으로 실행하는 헬퍼 함수 추가
def create_browser():
    options = Options()
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # 임시 프로필 디렉토리 사용
    import tempfile
    import os
    temp_dir = tempfile.mkdtemp()
    options.add_argument(f"--user-data-dir={temp_dir}")
    
    service = Service(executable_path=driver_path)
    options.add_argument(f"--remote-debugging-port=0")  # 랜덤 포트 사용
    options.binary_location = chrome_path
    
    # 추가 옵션
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(service=service, options=options)
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

def send_desktop_notification(title, message):
    try:
        notification.notify(
            title=title,
            message=message,
            timeout=10
        )
    except Exception as e:
        print(f"데스크톱 알림 발송 실패: {e}")

def calculate_interval(start_date_str):
    if start_date_str is None:
        # 아마도 에러
        send_telegram_sync(f"[Note] Error detected! {start_date_str}")
        return None
    try:
        if start_date_str.find("T") > 0:
            # 공백으로 구분된 시간대 처리
            if " " in start_date_str:
                date_part = start_date_str.replace(" ", "+").replace(":", "", 1)
                start_datetime = datetime.strptime(date_part, "%Y-%m-%dT%H:%M:%S%z")
            else:
                start_datetime = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%S%z")
        else:
            start_datetime = datetime.strptime(start_date_str + "T00:00:00+0900", "%Y-%m-%dT%H:%M:%S%z")
    except ValueError as e:
        send_telegram_sync(f"[Note] Date parsing error! {start_date_str}: {str(e)}")
        return random.uniform(2, 7)
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
        return current_hash, None
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
                        send_telegram_sync(message)
                        print(f"[{tag}] Change detected at:", time.ctime())
                        print(f"[{tag}] rtn_contents {ret}")
                else:
                    if validate_level_max == 1:
                        message = f"[{tag}] Change detected! {ret} at: {time.ctime()}"
                        send_telegram_sync(message)
    else:
        print(f"[{tag}] Detected same page")
    return new_hash, ret
