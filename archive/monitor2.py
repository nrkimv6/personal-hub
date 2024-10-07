import hashlib

import requests
import time

from kakao_message import send_message


def get_hash(url):
    response = requests.get(url)
    if response.status_code == 200:
        return hashlib.sha256(response.content).hexdigest(), response.content
    else:
        return None, None


#b'{"msg":"template_id can\'t be null.","code":-2}'
def monitor_url(url, interval=60):
    print("Starting URL monitor...")
    send_message("Starting URL monitor...", None)
    current_hash, current_content = get_hash(url)
    if current_hash is None:
        send_message("Failed to fetch URL content.", None)
        print("Failed to fetch URL content.")
        return

    try:
        while True:
            time.sleep(interval)
            new_hash, new_content = get_hash(url)
            if new_hash != current_hash:
                print("Change detected at:", time.ctime())
                print(f"new_hash {new_hash}")
                if( new_content != current_content):
                    send_message(f"Change detected at: {time.ctime()}", url)
                    print("Content also Change detected at:", time.ctime())
                    print(f"new_content {new_content}")
                # send_message(f"Change detected at: {time.ctime()}", url)
                current_hash = new_hash
                current_content = new_content
            else:
                print("No change detected.")
    except KeyboardInterrupt:
        print("Monitoring stopped.")
        send_message("Monitoring stopped.", None)

def test():
    # URL to monitor
    url = "https://booking.naver.com/booking/13/bizes/535509/items/3958951?area=ple&startDate=2024-06-21&theme=place"
    # monitor_url(url, interval=300)  # Check every 5 minutes
    monitor_url(url, interval=30)