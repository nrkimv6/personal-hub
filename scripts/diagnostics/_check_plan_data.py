"""plan_records / plan_events 진단 스크립트 (SQLite 전용 레거시 read-only).

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db 직접 접근을 사용합니다.
   2026-04-10 PostgreSQL 전환 이후에는 data/monitor.db가 운영 DB가 아닙니다.
   DB 파일이 존재하지 않으면 스크립트가 종료됩니다.
   현재 운영 DB 조회는 Admin API 또는 SQLAlchemy 세션 기반으로 수행하세요.
"""
import sqlite3
import sys
from pathlib import Path

_DB_PATH = Path("D:/work/project/tools/monitor-page/data/monitor.db")
if not _DB_PATH.exists():
    print(f"❌ SQLite DB를 찾을 수 없습니다: {_DB_PATH}")
    print("이 스크립트는 SQLite 전용 레거시입니다. 운영 DB 조회는 Admin API를 사용하세요.")
    sys.exit(1)

conn = sqlite3.connect(str(_DB_PATH))
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
