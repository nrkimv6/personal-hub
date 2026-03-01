import redis, time
r = redis.Redis(decode_responses=True)
hb = r.get("plan-runner:listener:heartbeat")
pid = r.get("plan-runner:listener:pid")
print(f"listener heartbeat: {hb}")
print(f"listener pid: {pid}")
if hb:
    diff = time.time() - float(hb)
    print(f"heartbeat age: {diff:.0f}s ago")
    print(f"alive: {diff < 30}")
else:
    print("listener NOT running (no heartbeat)")
