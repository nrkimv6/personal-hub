import redis, json
r = redis.Redis(decode_responses=True)
key = "plan-runner:merge-queue"
items = r.lrange(key, 0, -1)
r.delete(key)
kept = []
for raw in items:
    try:
        d = json.loads(raw)
        if "queued_at" in d or not d:
            print("제거:", raw[:80])
        else:
            kept.append(raw)
            r.rpush(key, raw)
    except Exception as e:
        print("빈 항목 제거:", repr(raw[:40]))
print(f"정리 완료: {len(items)-len(kept)}개 제거, {len(kept)}개 유지")
