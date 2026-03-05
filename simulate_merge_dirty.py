import redis
import json
import time
import os
from pathlib import Path

r = redis.Redis(decode_responses=True)
runner_id = "manual-test-41"

# Setup state
r.set(f"plan-runner:runners:{runner_id}:worktree_path", str(Path("D:/work/project/tools/monitor-page")))
r.set(f"plan-runner:runners:{runner_id}:branch", "plan/2026-03-05_fix-merge-error-logging")
r.set(f"plan-runner:runners:{runner_id}:plan_file", "docs/plan/2026-03-05_fix-merge-error-logging.md")
r.set(f"plan-runner:runners:{runner_id}:merge_status", "pending_merge") # Set to pending to trigger cleanup/merge check

print(f"Triggering merge for {runner_id}...")
r.set(f"plan-runner:runners:{runner_id}:merge_requested", "1")

# We don't need to send a command if we want the orphan scan to pick it up on startup
# but let's send a retry-merge command to make it fast
cmd = {
    "action": "retry-merge",
    "runner_id": runner_id,
    "command_id": "manual-41",
    "source": "cli"
}
r.lpush("plan-runner:commands", json.dumps(cmd))

print("Wait for listener to process...")
time.sleep(10)

status = r.get(f"plan-runner:runners:{runner_id}:merge_status")
print(f"Final status: {status}")

# Check merge results
history = r.lrange("plan-runner:merge-results", 0, 0)
if history:
    print(f"History entry: {history[0]}")
