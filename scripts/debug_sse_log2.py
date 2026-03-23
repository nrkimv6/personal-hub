"""log 이벤트만 타깃으로 더 긴 대기 테스트"""
import requests, threading, time, redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
events = []

def collect():
    try:
        with requests.get('http://localhost:8001/api/v1/dev-runner/events', stream=True, timeout=15) as resp:
            cur = 'message'
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    cur = 'message'
                    continue
                if line.startswith('event:'):
                    cur = line[6:].strip()
                elif line.startswith('data:'):
                    events.append((cur, line[5:].strip()))
                    print(f'  [recv] event={cur!r}')
                    if cur == 'log':
                        print(f'  [log data] {line[5:].strip()[:100]}')
                        return
    except Exception as e:
        print(f'error: {e}')

t = threading.Thread(target=collect, daemon=True)
t.start()
time.sleep(3.0)  # 더 오래 대기

print('[publish] logs channel')
n = r.publish('plan-runner:logs:debugtest2', '[TEST] log event test')
print(f'  subscribers: {n}')

t.join(timeout=5)
print(f'total: {len(events)}, log_events: {[e for e in events if e[0]=="log"]}')

# psubscribe 직접 확인
print()
print('--- Direct psubscribe test ---')
p = r.pubsub()
p.psubscribe('plan-runner:logs:*')
time.sleep(0.5)
r.publish('plan-runner:logs:direct_test', 'direct test message')
time.sleep(0.5)
msg = p.get_message(ignore_subscribe_messages=True, timeout=1.0)
print(f'direct psubscribe result: {msg}')
p.close()
