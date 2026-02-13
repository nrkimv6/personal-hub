import requests
import json
import time

# 스캔 시작
print("D:\\Archive 폴더 스캔 시작...")
response = requests.post(
    "http://localhost:8001/api/ic/scan/start",
    json={"root_folders": ["D:\\Archive"]}
)
print(f"응답: {response.status_code}")
print(response.json())

# 스캔 진행 상태 모니터링
print("\n스캔 진행 중...")
while True:
    time.sleep(5)
    status_response = requests.get("http://localhost:8001/api/ic/scan/status")
    status = status_response.json()

    if not status["is_running"]:
        print("\n스캔 완료!")
        print(f"폴더: {status['total_folders']}개")
        print(f"파일: {status['total_files']}개")
        if status["error"]:
            print(f"에러: {status['error']}")
        break

    print(f"진행률: {status['progress_percent']:.1f}% ({status['scanned_files']}/{status['total_files']} 파일)")
    print(f"현재: {status['current_folder']}")
