import sqlite3
conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db')
rows = conn.execute("SELECT id, name, target_type, enabled FROM task_schedules WHERE target_type IN ('plan_archive_analyze','plan_requirements_sync')").fetchall()
for r in rows:
    print(r)
conn.close()
