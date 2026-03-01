"""E2E: 존재하지 않는 plan_file로 runner 시작 → 에러 publish 검증"""
import requests
import threading
import time
import json
import redis

BASE = "http://localhost:8001/api/v1/dev-runner"

# 1. SSE subscriber를 먼저 준비 (pub/sub 직접 구독)
r = redis.Redis(decode_responses=True)
received = []
runner_id_holder = [None]
stop_event = threading.Event()


def subscriber():
    """runner_id가 설정되면 해당 채널 구독"""
    while not stop_event.is_set():
        if runner_id_holder[0]:
            break
        time.sleep(0.05)

    if not runner_id_holder[0]:
        return

    channel = f"plan-runner:logs:{runner_id_holder[0]}"
    ps = r.pubsub()
    ps.subscribe(channel)
    deadline = time.time() + 10
    for msg in ps.listen():
        if time.time() > deadline:
            break
        if msg["type"] == "message":
            received.append(msg["data"])
            if "[ERROR]" in msg["data"]:
                break
    ps.unsubscribe()


t = threading.Thread(target=subscriber, daemon=True)
t.start()

# 2. 존재하지 않는 plan file로 실행 요청
print("=== Sending run request with non-existent plan file ===")
resp = requests.post(
    f"{BASE}/run",
    json={
        "plan_file": "D:/work/project/tools/monitor-page/docs/plan/NONEXISTENT_TEST_E2E.md",
        "engine": "claude",
    },
    timeout=10,
)
print(f"Response: {resp.status_code} {resp.text[:200]}")
result = resp.json()
runner_id = result.get("runner_id", "")
runner_id_holder[0] = runner_id
print(f"Runner ID: {runner_id}")

if not runner_id:
    print("FAIL: No runner_id returned")
    exit(1)

# 3. Wait for error to propagate
time.sleep(5)
stop_event.set()
t.join(timeout=3)

# 4. Check Redis state
status = r.get(f"plan-runner:runners:{runner_id}:status")
error = r.get(f"plan-runner:runners:{runner_id}:error")
print(f"\n=== Redis state ===")
print(f"status: {status}")
print(f"error: {error}")

# 5. Check pub/sub received
print(f"\n=== Pub/Sub received ===")
for line in received:
    print(f"  {line}")

# 6. Check via SSE/recent logs API
try:
    resp3 = requests.get(
        f"{BASE}/logs/recent?runner_id={runner_id}&lines=10", timeout=5
    )
    if resp3.status_code == 200:
        data = resp3.json()
        print(f"\n=== Recent logs API ===")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
except Exception as e:
    print(f"Recent logs API error: {e}")

# 7. Summary
print(f"\n=== RESULT ===")
has_error_status = status == "error"
has_error_msg = error is not None and len(error) > 0
has_pubsub = any("[ERROR]" in m for m in received)
print(f"Error status in Redis: {'PASS' if has_error_status else 'FAIL'}")
print(f"Error message in Redis: {'PASS' if has_error_msg else 'FAIL'}")
print(f"Error published to pub/sub: {'PASS' if has_pubsub else 'FAIL'}")
print(f"ALL PASS: {has_error_status and has_error_msg and has_pubsub}")

# Cleanup: dismiss the test runner tab
try:
    requests.delete(f"{BASE}/runners/{runner_id}/tab", timeout=5)
    print(f"\nCleaned up test runner {runner_id}")
except Exception:
    pass
