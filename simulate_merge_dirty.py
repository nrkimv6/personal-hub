import redis
import json
import time
import os
from pathlib import Path

r = redis.Redis(decode_responses=True)
runner_id = "test-dirty-merge"

# Clean up previous state
r.delete(f"plan-runner:runners:{runner_id}:merge_requested")
r.delete(f"plan-runner:runners:{runner_id}:merge_status")

# Setup state
r.set(f"plan-runner:runners:{runner_id}:worktree_path", str(Path("D:/work/project/tools/monitor-page"))) # Just use root as worktree for mock
r.set(f"plan-runner:runners:{runner_id}:branch", "plan/2026-03-05_fix-merge-error-logging")
r.set(f"plan-runner:runners:{runner_id}:plan_file", "docs/plan/2026-03-05_fix-merge-error-logging.md")

print(f"Triggering merge for {runner_id}...")
r.set(f"plan-runner:runners:{runner_id}:merge_requested", "1")

# Wait and watch log
print("Wait for listener to process...")
time.sleep(5)

status = r.get(f"plan-runner:runners:{runner_id}:merge_status")
print(f"Final status: {status}")

# Check merge results
history = r.lrange("plan-runner:merge-results", 0, 0)
if history:
    print(f"History entry: {history[0]}")
