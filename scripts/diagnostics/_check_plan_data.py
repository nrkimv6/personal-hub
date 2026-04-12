import sqlite3
conn = sqlite3.connect('D:/work/project/tools/monitor-page/data/monitor.db')
conn.row_factory = sqlite3.Row

print('=== plan_records (최근 30개) ===')
rows = conn.execute('SELECT id, file_path, status, created_at FROM plan_records ORDER BY id DESC LIMIT 30').fetchall()
for r in rows:
    print(f'id={r["id"]} path={r["file_path"]} status={r["status"]} created={r["created_at"]}')

print()
print('=== plan_events (최근 30개) ===')
rows = conn.execute('SELECT pe.id, pe.plan_record_id, pe.event_type, pe.created_at, pr.file_path FROM plan_events pe LEFT JOIN plan_records pr ON pe.plan_record_id=pr.id ORDER BY pe.id DESC LIMIT 30').fetchall()
for r in rows:
    print(f'id={r["id"]} plan_id={r["plan_record_id"]} type={r["event_type"]} path={r["file_path"]} created={r["created_at"]}')

print()
print('=== 전체 카운트 ===')
total_records = conn.execute('SELECT COUNT(*) FROM plan_records').fetchone()[0]
total_events = conn.execute('SELECT COUNT(*) FROM plan_events').fetchone()[0]
print(f'plan_records: {total_records}, plan_events: {total_events}')

print()
print('=== file_path 패턴 (상위 30개) ===')
rows = conn.execute('SELECT file_path, COUNT(*) as cnt FROM plan_records GROUP BY file_path ORDER BY cnt DESC LIMIT 30').fetchall()
for r in rows:
    print(f'cnt={r["cnt"]} path={r["file_path"]}')

print()
print('=== Temp/Test 경로 의심 레코드 ===')
rows = conn.execute("SELECT id, file_path, created_at FROM plan_records WHERE file_path LIKE '%tmp%' OR file_path LIKE '%test%' OR file_path LIKE '%pytest%' OR file_path LIKE '%AppData%' OR file_path IS NULL ORDER BY id DESC LIMIT 30").fetchall()
for r in rows:
    print(f'id={r["id"]} path={r["file_path"]} created={r["created_at"]}')

conn.close()
