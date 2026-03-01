import redis, json
r = redis.Redis(decode_responses=True)

# Check pending commands
pending = r.lrange("plan-runner:commands", 0, -1)
print(f"Pending commands: {len(pending)}")
for cmd in pending:
    try:
        data = json.loads(cmd)
        print(f"  runner_id={data.get('runner_id')} action={data.get('action')} plan={data.get('plan_file','')[-50:]}")
    except Exception:
        print(f"  raw: {cmd[:100]}")

# Check all runner keys
import fnmatch
keys = r.keys("plan-runner:runners:*")
runners = {}
for k in keys:
    parts = k.split(":")
    if len(parts) >= 4:
        rid = parts[2]
        field = parts[3]
        if rid not in runners:
            runners[rid] = {}
        runners[rid][field] = r.get(k)

print(f"\nRunner states ({len(runners)}):")
for rid, fields in sorted(runners.items()):
    print(f"  {rid}: {fields}")
