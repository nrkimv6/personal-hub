"""E2E: 존재하지 않는 plan_file로 runner 시작 → 에러 publish 검증"""
import requests
import threading
import time
import json
import redis

BASE = "http://localhost:8001/api/v1/dev-runner"

r = redis.Redis(decode_responses=True)
received = []
stop_event = threading.Event()

# 1. 먼저 stale 브랜치 정리
import subprocess
try:
    subprocess.run(
        ["git", "branch", "-D", "plan/NONEXISTENT_TEST_E2E_V2"],
        cwd="D:/work/project/tools/monitor-page",
        capture_output=True,
    )
except Exception:
    pass


def subscriber():
    """패턴 구독으로 모든 runner 로그 수신 — runner_id 몰라도 OK"""
    ps = r.pubsub()
    ps.psubscribe("plan-runner:logs:*")
    deadline = time.time() + 15
    for msg in ps.listen():
        if time.time() > deadline or stop_event.is_set():
            break
        if msg["type"] == "pmessage":
            received.append({"channel": msg["channel"], "data": msg["data"]})
            if "[ERROR]" in msg["data"]:
                break
    ps.punsubscribe()


t = threading.Thread(target=subscriber, daemon=True)
t.start()
time.sleep(0.5)  # 구독이 확실히 걸릴 때까지 대기

# 2. 존재하지 않는 plan file로 실행 요청
PLAN = "D:/work/project/tools/monitor-page/docs/plan/NONEXISTENT_TEST_E2E_V2.md"
print("=== Sending run request with non-existent plan file ===")
resp = requests.post(
    f"{BASE}/run",
    json={"plan_file": PLAN, "engine": "claude"},
    timeout=10,
)
print(f"Response: {resp.status_code} {resp.text[:200]}")
result = resp.json()
runner_id = result.get("runner_id", "")
print(f"Runner ID: {runner_id}")

if not runner_id:
    print("FAIL: No runner_id returned")
    exit(1)

# 3. Wait for error to propagate
time.sleep(8)
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
for item in received:
    print(f"  [{item['channel']}] {item['data'][:200]}")

# 6. Summary
has_error_status = status == "error"
has_error_msg = error is not None and len(error) > 0
has_pubsub = any("[ERROR]" in m["data"] for m in received)
print(f"\n=== RESULT ===")
print(f"Error status in Redis: {'PASS' if has_error_status else 'FAIL'}")
print(f"Error message in Redis: {'PASS' if has_error_msg else 'FAIL'}")
print(f"Error published to pub/sub: {'PASS' if has_pubsub else 'FAIL'}")
all_pass = has_error_status and has_error_msg and has_pubsub
print(f"ALL PASS: {all_pass}")

# Cleanup
try:
    requests.delete(f"{BASE}/runners/{runner_id}/tab", timeout=5)
    print(f"\nCleaned up test runner {runner_id}")
except Exception:
    pass
