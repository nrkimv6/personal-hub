import requests, threading, time, redis, json

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
events = []

def collect():
    try:
        with requests.get('http://localhost:8001/api/v1/dev-runner/events', stream=True, timeout=10) as resp:
            cur = 'message'
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    cur = 'message'
                    continue
                if line.startswith('event:'):
                    cur = line[6:].strip()
                elif line.startswith('data:'):
                    events.append((cur, line[5:].strip()))
                    print(f'  [recv] event={cur!r} data={line[5:].strip()[:80]!r}')
                    if len(events) >= 6:
                        return
    except Exception as e:
        print(f'collect error: {e}')

t = threading.Thread(target=collect, daemon=True)
t.start()
time.sleep(2.0)

print('[publish] plan-runner:logs:debugtest → "[TEST] debug log line"')
n = r.publish('plan-runner:logs:debugtest', '[TEST] debug log line')
print(f'  subscribers: {n}')
time.sleep(2)

print('[publish] plan-runner:merge-log:debugtest → "[MERGE] debug merge line"')
n = r.publish('plan-runner:merge-log:debugtest', '[MERGE] debug merge line')
print(f'  subscribers: {n}')
time.sleep(2)

t.join(timeout=1)
print(f'total events: {len(events)}')
log_events = [e for e in events if e[0] in ('log', 'log_completed', 'merge_log', 'merge_log_completed')]
print(f'log-type events: {log_events}')
