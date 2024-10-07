import hashlib
import time



def get_hash(driver, url, repeat_cnt=0, create_browser=None):
    try:
        driver.get(url)
        time.sleep(5)

        page_content = driver.page_source
        page_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()
        return driver, page_hash, page_content
    except Exception as e:
        print(f"Error fetching the URL: {e}")
        new_driver = create_browser()
        if repeat_cnt == 0:
            return get_hash(new_driver, url, repeat_cnt=1)
        return new_driver, None, None

