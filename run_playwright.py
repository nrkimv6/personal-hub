import random
import time
import asyncio
from datetime import datetime
from pathlib import Path
import re
import os

import playwright.async_api as pw
from plyer import notification

from telegram_message import send_telegram_notification
from urls import urls
from valid_check import is_content_valid

# Configuration
user_data_dir = Path(r"C:\Users\Narang\AppData\Local\Google\Chrome\User Data")
profile_dir = "Default"

# Use this to store browser state instead of user profile
state_path = Path("./browser_state.json")


async def send_telegram_notification_wrapper(message):
    try:
        await send_telegram_notification(message)
    except Exception as e:
        print(f"텔레그램 발송 실패: {str(e)}")


def send_desktop_notification(title, message):
    try:
        # Windows 알림 시스템은 메시지 길이에 256자 제한이 있으므로 메시지를 잘라냅니다
        if len(message) > 256:
            message = message[:253] + "..."
            
        notification.notify(
            title=title,
            message=message,
            timeout=10
        )
    except Exception as e:
        print(f"데스크톱 알림 발송 실패: {e}")


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
        # 아마도 에러
        asyncio.create_task(send_telegram_notification_wrapper(f"[Note] Error detected! {start_date_str}"))
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
        asyncio.create_task(
            send_telegram_notification_wrapper(f"[Note] Date parsing error! {start_date_str}: {str(e)}"))
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


async def get_hash(page, url):
    try:
        print(f"[DEBUG] get_hash 시작: URL={url}")
        print(f"[DEBUG] page 객체 타입: {type(page)}")
        print(f"[DEBUG] page.goto 메서드 타입: {type(page.goto)}")
        
        await page.goto(url, wait_until="networkidle", timeout=30000)
        print(f"[DEBUG] 페이지 로딩 완료")
        
        # 현재 URL 확인
        current_url = page.url
        print(f"Page URL: {current_url}")
        
        # 에러 페이지 감지
        if "error" in current_url or "invalidBusiness" in current_url:
            error_message = f"[ERROR] 에러 페이지로 리다이렉트됨: {current_url}"
            print(error_message)
            
            # 에러 페이지 타입 확인
            error_type = "알 수 없음"
            if "invalidBusiness" in current_url:
                error_type = "유효하지 않은 비즈니스"
            elif "error" in current_url:
                error_type = "일반 오류"
                
            # 에러 페이지 스크린샷 저장 (선택적)
            try:
                screenshot_path = f"error_screenshots/error_{int(time.time())}.png"
                os.makedirs("error_screenshots", exist_ok=True)
                await page.screenshot(path=screenshot_path)
                print(f"[DEBUG] 에러 페이지 스크린샷 저장: {screenshot_path}")
            except Exception as e:
                print(f"[WARNING] 스크린샷 저장 실패: {e}")
                
            # 데스크톱 알림 발송
            send_desktop_notification(
                "에러 페이지 감지", 
                f"URL: {url}\n에러 타입: {error_type}\n리다이렉트 URL: {current_url}"
            )
            
            return None, None
        
        # title 속성 접근 방식 수정
        try:
            page_title = await page.title()
            print(f"Page Title: {page_title}")
        except Exception as e:
            print(f"[WARNING] 페이지 제목 가져오기 실패: {e}")
            page_title = "제목 없음"
        
        content = await page.content()
        print(f"[DEBUG] 페이지 콘텐츠 추출 완료, 길이: {len(content)}")
        
        print(f"[DEBUG] hash 함수 타입: {type(hash)}")
        content_hash = hash(content)
        print(f"[DEBUG] 해시 계산 완료: {content_hash}")
        
        return content_hash, content
    except Exception as e:
        print(f"Error getting hash: {e}")
        print(f"[DEBUG] 예외 타입: {type(e)}")
        import traceback
        print(f"[DEBUG] 예외 스택트레이스: {traceback.format_exc()}")
        return None, None


# 시간과 매수를 파싱하는 함수 추가
def parse_time_and_stock(button_text):
    """
    버튼 텍스트에서 시간과 매수를 파싱합니다.
    예: "오전 11:001매" -> ("오전 11:00", "1")
    """
    # 시간 패턴 (오전/오후 HH:MM)
    time_pattern = r'(오전|오후)\s+\d{1,2}:\d{2}'
    time_match = re.search(time_pattern, button_text)
    time_str = time_match.group(0) if time_match else ""
    
    # 매수 패턴 (숫자+매)
    stock_pattern = r'(\d+)매'
    stock_match = re.search(stock_pattern, button_text)
    stock_str = stock_match.group(1) if stock_match else "0"
    
    return time_str, stock_str


async def perform_task(browser_context, url, tag, current_hash, current_data, validate_level=2):
    print(f"[{tag}] perform_task at: {time.ctime()}")
    print(f"[DEBUG] perform_task 시작: URL={url}, tag={tag}, current_hash={current_hash}")
    print(f"[DEBUG] browser_context 타입: {type(browser_context)}")

    try:
        # browser_context가 Page 객체인 경우 (browser7.py에서 호출될 때)
        if hasattr(browser_context, 'goto'):
            page = browser_context
        else:
            # browser_context가 BrowserContext 객체인 경우 (run_playwright.py에서 직접 호출될 때)
            page = await browser_context.new_page()
            
        new_hash, new_content = await get_hash(page, url)
        if new_hash is None:
            print("Fatal error getting hash!")
            if not hasattr(browser_context, 'goto'):
                await page.close()
            return current_hash, None

        validate_level_max = 2
        try:
            validate_level_max = int(validate_level)
            print(f"[{tag}] validate to {validate_level_max}")
        except:
            print(f"[{tag}] using default validate level {validate_level_max}")

        ret = None
        if new_hash != current_hash:
            if validate_level_max > 0:
                ret = is_content_valid(new_content, validate_level_max)
                if ret is None:
                    print(f"[{tag}] Detected the inactive page message, not sending update.")
                else:
                    if len(ret) > 0:
                        if current_data == ret:
                            print(f"[{tag}] same with prev")
                        else:
                            # 시간과 매수 정보 파싱
                            time_changes = []
                            stock_changes = []
                            
                            for button_text in ret:
                                time_str, stock_str = parse_time_and_stock(button_text)
                                if time_str:
                                    time_changes.append(time_str)
                                if stock_str:
                                    stock_changes.append(f"{time_str}: {stock_str}매")
                            
                            # 텔레그램 메시지 (시간만)
                            if time_changes:
                                telegram_message = f"[{tag}] 시간 변경 감지: {', '.join(time_changes)} at: {time.ctime()}"
                                await send_telegram_notification(telegram_message)
                            
                            # 데스크톱 메시지 (시간과 매수)
                            if stock_changes:
                                desktop_message = f"[{tag}] 변경 감지: {', '.join(stock_changes)} at: {time.ctime()}"
                                send_desktop_notification(f"[{tag}] 변경 감지", desktop_message)
                            
                            print(f"[{tag}] Change detected at:", time.ctime())
                            print(f"[{tag}] rtn_contents {ret}")
                    else:
                        if validate_level_max == 1:
                            message = f"[{tag}] Change detected! {ret} at: {time.ctime()}"
                            await send_telegram_notification(message)
        else:
            print(f"[{tag}] Detected same page")

        if not hasattr(browser_context, 'goto'):
            await page.close()
        return new_hash, ret
    except Exception as e:
        print(f"Error in perform_task: {e}")
        if not hasattr(browser_context, 'goto'):
            await page.close()
        return current_hash, None


async def monitor_url(browser_context, url, tag, interval_override=None):
    current_hash = ""
    current_data = None

    while True:
        try:
            start_date = extract_date_from_url(url)
            interval = calculate_interval(start_date) if interval_override is None else interval_override

            if interval is None:
                # Error occurred, use default interval
                interval = random.uniform(10, 20)

            print(f"[{tag}] Sleeping for {interval:.2f} seconds")
            await asyncio.sleep(interval)

            current_hash, current_data = await perform_task(
                browser_context, url, tag, current_hash, current_data
            )

        except Exception as e:
            print(f"Error in monitor_url loop: {e}")
            await asyncio.sleep(10)  # Sleep on error and retry


async def main():
    # Launch browser with persistent storage for auth tokens
    async with pw.async_playwright() as playwright:
        # Use persistent context if you need to maintain login sessions
        browser_context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir / profile_dir,
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--window-size=1920,1080',
            ],
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        # Alternative approach using saved state instead of profile
        # This is recommended over using user profiles
        """
        # Using browser and context with saved state
        browser = await playwright.chromium.launch(headless=False)

        # Load previously saved state if exists
        if state_path.exists():
            browser_context = await browser.new_context(storage_state=state_path)
        else:
            browser_context = await browser.new_context()

            # Log in manually first time (you might need to add code here)
            page = await browser_context.new_page()
            await page.goto("https://your-login-url.com")
            # ... add login steps here if needed

            # Wait for user input to confirm login is complete
            input("Please complete login in the browser and press Enter...")

            # Save auth state for future runs
            await browser_context.storage_state(path=state_path)
            await page.close()
        """

        # Start monitoring tasks
        tasks = []
        for i, (url, tag) in enumerate(urls):
            task = asyncio.create_task(monitor_url(browser_context, url, tag))
            tasks.append(task)

        # Wait for all tasks
        await asyncio.gather(*tasks)

        # Cleanup - only need to close the context, playwright closes automatically with context manager
        await browser_context.close()


if __name__ == "__main__":
    asyncio.run(main())