"""SQLite 마이그레이션 SQL 파일 적용 스크립트 (SQLite 전용 레거시).

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db에 직접 SQL을 실행합니다.
   2026-04-10 PostgreSQL 전환 이후에는 data/monitor.db가 운영 DB가 아닙니다.
   DB 파일이 존재하지 않으면 스크립트가 종료됩니다.
   PostgreSQL 환경에서 마이그레이션이 필요하면 psql 또는 Alembic을 사용하세요.

실행 방법 (SQLite 레거시 환경에서만):
    python scripts/migrations/apply_migration.py [migration_file.sql]
"""
import sqlite3
import os
import sys
from pathlib import Path

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(project_root)

db_path = Path(project_root) / "data" / "monitor.db"
if not db_path.exists():
    print(f"❌ SQLite DB를 찾을 수 없습니다: {db_path}")
    print("이 스크립트는 SQLite 전용 레거시입니다. data/monitor.db가 없으면 실행하지 마세요.")
    print("PostgreSQL 환경에서는 psql 또는 Alembic을 사용하세요.")
    sys.exit(1)

migration_file = sys.argv[1] if len(sys.argv) > 1 else "app/migrations/041_create_daily_stats_tables.sql"

print(f"Applying migration: {migration_file}")
print(f"Working directory: {os.getcwd()}")
print(f"⚠️  LEGACY: SQLite DB에 직접 실행합니다: {db_path}")

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

with open(migration_file, "r", encoding="utf-8") as f:
    sql = f.read()

try:
    cursor.executescript(sql)
    print("Migration executed successfully!")
except Exception as e:
    print(f"Error during migration: {e}")

conn.commit()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('proxy_daily_stats', 'monitoring_daily_stats', 'maintenance_runs')")
tables = cursor.fetchall()
print(f"Created tables: {[t[0] for t in tables]}")

conn.close()
print("Migration completed!")
