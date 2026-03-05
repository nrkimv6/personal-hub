import redis
import json
import time
import os
from pathlib import Path

r = redis.Redis(decode_responses=True)
runner_id = "test-41-real"

# Setup state
r.set(f"plan-runner:runners:{runner_id}:worktree_path", str(Path("D:/work/project/tools/monitor-page")))
r.set(f"plan-runner:runners:{runner_id}:branch", "test/dirty-merge-branch")
r.set(f"plan-runner:runners:{runner_id}:plan_file", "docs/plan/2026-03-05_fix-merge-error-logging.md")

print(f"Triggering merge for {runner_id}...")
r.set(f"plan-runner:runners:{runner_id}:merge_requested", "1")

cmd = {
    "action": "retry-merge",
    "runner_id": runner_id,
    "command_id": "manual-41-real",
    "source": "cli"
}
r.lpush("plan-runner:commands", json.dumps(cmd))

print("Wait for listener to process...")
time.sleep(15)

status = r.get(f"plan-runner:runners:{runner_id}:merge_status")
print(f"Final status: {status}")

# Check merge results
history = r.lrange("plan-runner:merge-results", 0, 0)
if history:
    print(f"History entry: {history[0]}")
