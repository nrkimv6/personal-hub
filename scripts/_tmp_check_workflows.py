import sqlite3
conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db')
rows = conn.execute(
    "SELECT id, slug, status, runner_id, worktree_path, branch, created_at FROM workflows WHERE status IN ('planned','running','merge_pending','merging') ORDER BY created_at DESC"
).fetchall()
print(f"총 {len(rows)}개")
for r in rows:
    print(r)

# worktree 실제 존재 여부도 확인
import os
print("\n--- worktree 존재 여부 ---")
for r in rows:
    wt = r[4]
    if wt:
        exists = os.path.isdir(wt)
        print(f"  {r[1][:40]} | {r[2]} | worktree={'EXISTS' if exists else 'MISSING'} | {wt}")
    else:
        print(f"  {r[1][:40]} | {r[2]} | worktree=None")

conn.close()
