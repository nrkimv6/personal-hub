"""
마이그레이션 적용 스크립트
"""
import sqlite3
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(project_root)

migration_file = sys.argv[1] if len(sys.argv) > 1 else "app/migrations/041_create_daily_stats_tables.sql"

print(f"Applying migration: {migration_file}")
print(f"Working directory: {os.getcwd()}")

conn = sqlite3.connect("data/monitor.db")
cursor = conn.cursor()

with open(migration_file, "r", encoding="utf-8") as f:
    sql = f.read()

# executescript로 전체 실행
try:
    cursor.executescript(sql)
    print("Migration executed successfully!")
except Exception as e:
    print(f"Error during migration: {e}")

conn.commit()

# 테이블 확인
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('proxy_daily_stats', 'monitoring_daily_stats', 'maintenance_runs')")
tables = cursor.fetchall()
print(f"Created tables: {[t[0] for t in tables]}")

conn.close()
print("Migration completed!")
