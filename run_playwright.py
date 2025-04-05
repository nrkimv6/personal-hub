import random
import time
import asyncio
from datetime import datetime
from pathlib import Path

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
        await page.goto(url, wait_until="networkidle", timeout=30000)
        content = await page.content()
        print(f"Page URL: {await page.url()}")
        print(f"Page Title: {await page.title()}")
        return hash(content), content
    except Exception as e:
        print(f"Error getting hash: {e}")
        return None, None


async def perform_task(browser_context, url, tag, current_hash, current_data, validate_level=2):
    print(f"[{tag}] perform_task at: {time.ctime()}")

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
                            message = f"[{tag}] Change detected with ret {ret} at: {time.ctime()}"
                            await send_telegram_notification(message)
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