"""마이그레이션 적용 스크립트"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "monitor.db"
MIGRATIONS_DIR = Path(__file__).parent / "app" / "migrations"

def apply_migration(migration_file: Path):
    """마이그레이션 파일 적용"""
    print(f"[*] Applying migration: {migration_file.name}")

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        # 여러 SQL 문을 실행
        cursor.executescript(sql_content)
        conn.commit()
        print(f"[+] Successfully applied: {migration_file.name}")
    except Exception as e:
        print(f"[!] Error applying {migration_file.name}: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def main():
    """메인 함수"""
    # 089, 090 마이그레이션 적용
    migrations = [
        "089_writing_batches.sql",
        "090_llm_requests_writing_columns.sql",
    ]

    for migration_name in migrations:
        migration_file = MIGRATIONS_DIR / migration_name
        if migration_file.exists():
            apply_migration(migration_file)
        else:
            print(f"[!] Migration file not found: {migration_name}")

    print("\n[+] All migrations applied successfully!")

if __name__ == "__main__":
    main()
