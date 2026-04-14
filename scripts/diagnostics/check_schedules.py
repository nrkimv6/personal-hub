#!/usr/bin/env python3
"""스케줄 상태 확인 스크립트."""
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db')
cursor = conn.cursor()

# 테이블 스키마 확인
print("=" * 80)
print("task_schedules schema")
print("=" * 80)
cursor.execute("PRAGMA table_info(task_schedules)")
for row in cursor.fetchall():
    print(row)
print()

# 모든 활성 스케줄 확인 (task_schedules 테이블)
cursor.execute('SELECT * FROM task_schedules WHERE enabled = 1')
rows = cursor.fetchall()
columns = [d[0] for d in cursor.description]

print("=" * 80)
print("Active Schedules")
print("=" * 80)

for row in rows:
    d = dict(zip(columns, row))
    print(f"ID: {d.get('id')}, Name: {d.get('name')}, Type: {d.get('target_type')}")
    config = json.loads(d.get('target_config', '{}')) if d.get('target_config') else {}
    print(f"  time_windows: {config.get('time_windows', [])}")
    print(f"  daily_runs: {config.get('daily_runs', 'N/A')}")
    print(f"  min_interval_hours: {config.get('min_interval_hours', 'N/A')}")
    print(f"  Last: {d.get('last_run_at')}")
    print(f"  Next: {d.get('next_run_at')}")
    print()

# 최근 스케줄 실행 이력 확인
print("=" * 80)
print("Recent Schedule Runs (last 20)")
print("=" * 80)

cursor.execute('''
    SELECT r.id, s.name, s.target_type, r.status, r.started_at, r.completed_at, r.stop_reason
    FROM task_schedule_runs r
    JOIN task_schedules s ON r.schedule_id = s.id
    ORDER BY r.id DESC
    LIMIT 20
''')
rows = cursor.fetchall()
columns = [d[0] for d in cursor.description]

for row in rows:
    d = dict(zip(columns, row))
    print(f"Run #{d['id']}: {d['name']} ({d['target_type']})")
    print(f"  Status: {d['status']}, Started: {d['started_at']}, Completed: {d['completed_at']}")
    print(f"  Reason: {d['stop_reason']}")
    print()

conn.close()
