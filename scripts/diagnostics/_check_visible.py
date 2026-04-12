"""임시 스크립트: Redis에서 visible runner 잔류 확인"""
import redis

r = redis.Redis(decode_responses=True)
active = r.smembers("plan-runner:active_runners")
recent = r.zrange("plan-runner:recent_runners", 0, -1)
all_ids = active | set(recent)

print(f"Active: {active}")
print(f"Recent: {recent}")
print(f"All: {all_ids}")

for rid in all_ids:
    trigger = r.get(f"plan-runner:runners:{rid}:trigger")
    status = r.get(f"plan-runner:runners:{rid}:status")
    is_visible = trigger in ("user", "user:all")
    print(f"  {rid}: trigger={trigger}, status={status}, visible={is_visible}")

# tc-pytest- prefix 키 확인
keys = r.keys("plan-runner:runners:*")
print(f"\nAll runner keys ({len(keys)}):")
for k in sorted(keys):
    print(f"  {k} = {r.get(k)}")
