"""
데이터베이스 마이그레이션 스크립트

기존 테이블에 새 컬럼을 추가하고, 새 테이블을 생성합니다.

사용법:
    python scripts/migrate_db.py
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError
from app.config import settings
from app.database import Base


def get_engine():
    """데이터베이스 엔진 생성"""
    db_url = settings.DATABASE_URL
    return create_engine(db_url, connect_args={"check_same_thread": False})


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """컬럼이 존재하는지 확인"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(engine, table_name: str) -> bool:
    """테이블이 존재하는지 확인"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def migrate_monitor_targets(engine):
    """monitor_targets 테이블에 예약 관련 컬럼 추가"""
    print("\n📋 monitor_targets 테이블 마이그레이션...")

    new_columns = [
        ("auto_booking_enabled", "BOOLEAN DEFAULT 0"),
        ("max_bookings", "INTEGER DEFAULT 1"),
        ("booking_count", "INTEGER DEFAULT 0"),
        ("time_range", "TEXT"),
        ("last_booking_time", "TIMESTAMP"),
        ("booking_options", "TEXT"),
    ]

    with engine.connect() as conn:
        for col_name, col_def in new_columns:
            if not column_exists(engine, "monitor_targets", col_name):
                try:
                    sql = f"ALTER TABLE monitor_targets ADD COLUMN {col_name} {col_def}"
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"  ✅ {col_name} 컬럼 추가됨")
                except OperationalError as e:
                    print(f"  ⚠️ {col_name} 컬럼 추가 실패: {e}")
            else:
                print(f"  ℹ️ {col_name} 컬럼 이미 존재")


def create_booking_history_table(engine):
    """booking_history 테이블 생성"""
    print("\n📋 booking_history 테이블 생성...")

    if table_exists(engine, "booking_history"):
        print("  ℹ️ booking_history 테이블 이미 존재")
        return

    sql = """
    CREATE TABLE IF NOT EXISTS booking_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER,
        url TEXT NOT NULL,
        tag TEXT NOT NULL,
        slot_datetime TEXT NOT NULL,
        slot_info TEXT,
        success BOOLEAN DEFAULT 0,
        error_message TEXT,
        business_id TEXT,
        item_id TEXT,
        category TEXT,
        booking_method TEXT DEFAULT 'parallel',
        dry_run BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        booking_started_at TIMESTAMP,
        booking_completed_at TIMESTAMP,
        FOREIGN KEY (target_id) REFERENCES monitor_targets(id)
    )
    """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        print("  ✅ booking_history 테이블 생성됨")


def create_business_options_table(engine):
    """business_options 테이블 생성"""
    print("\n📋 business_options 테이블 생성...")

    if table_exists(engine, "business_options"):
        print("  ℹ️ business_options 테이블 이미 존재")
        return

    sql = """
    CREATE TABLE IF NOT EXISTS business_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id TEXT NOT NULL UNIQUE,
        business_name TEXT,
        option_config TEXT,
        auto_fill_config TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        print("  ✅ business_options 테이블 생성됨")


def create_monitoring_logs_table(engine):
    """monitoring_logs 테이블 생성"""
    print("\n📋 monitoring_logs 테이블 생성...")

    if table_exists(engine, "monitoring_logs"):
        print("  ℹ️ monitoring_logs 테이블 이미 존재")
        return

    sql = """
    CREATE TABLE IF NOT EXISTS monitoring_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER,
        url TEXT NOT NULL,
        tag TEXT NOT NULL,
        status TEXT NOT NULL,
        available_slots_count INTEGER DEFAULT 0,
        available_slots TEXT,
        data_hash TEXT,
        hash_changed BOOLEAN DEFAULT 0,
        api_response TEXT,
        error_message TEXT,
        response_time_ms REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (target_id) REFERENCES monitor_targets(id)
    )
    """

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        print("  ✅ monitoring_logs 테이블 생성됨")


def insert_default_business_options(engine):
    """기본 사업자 옵션 데이터 삽입"""
    print("\n📋 기본 사업자 옵션 데이터 삽입...")

    import json

    default_options = [
        {
            "business_id": "142806",
            "business_name": "전통주갤러리",
            "option_config": json.dumps({
                "options": [0],  # 첫 번째 옵션 선택
                "items": {}
            }),
            "auto_fill_config": json.dumps({
                "type": "dropdown_and_textarea",
                "steps": [
                    {"type": "dropdown", "index": 0, "value_index": 1},
                    {"type": "dropdown", "index": 1, "value_index": 1},
                    {"type": "textarea", "selector": "textarea#extra2", "value": "auto_user_name"}
                ]
            })
        },
        {
            "business_id": "1269828",
            "business_name": "향기 사업자",
            "option_config": json.dumps({
                "options": [0],
                "items": {
                    "6308953": {"options": [0, 1]}
                }
            }),
            "auto_fill_config": json.dumps({
                "type": "placeholder_inputs",
                "fields": [
                    {"index": 0, "value": "auto_user_name"},
                    {"index": 1, "value": "4216"},
                    {"index": 2, "value": "네"},
                    {"index": 3, "value": "네"}
                ]
            })
        }
    ]

    with engine.connect() as conn:
        for opt in default_options:
            # 이미 존재하는지 확인
            check_sql = text("SELECT id FROM business_options WHERE business_id = :bid")
            result = conn.execute(check_sql, {"bid": opt["business_id"]}).fetchone()

            if result:
                print(f"  ℹ️ {opt['business_name']} ({opt['business_id']}) 이미 존재")
                continue

            insert_sql = text("""
                INSERT INTO business_options (business_id, business_name, option_config, auto_fill_config)
                VALUES (:business_id, :business_name, :option_config, :auto_fill_config)
            """)
            conn.execute(insert_sql, opt)
            conn.commit()
            print(f"  ✅ {opt['business_name']} ({opt['business_id']}) 추가됨")


def main():
    """메인 마이그레이션 함수"""
    print("=" * 50)
    print("🚀 데이터베이스 마이그레이션 시작")
    print("=" * 50)

    engine = get_engine()
    print(f"\n데이터베이스: {settings.DATABASE_URL}")

    try:
        # 1. monitor_targets 컬럼 추가
        migrate_monitor_targets(engine)

        # 2. 새 테이블 생성
        create_booking_history_table(engine)
        create_business_options_table(engine)
        create_monitoring_logs_table(engine)

        # 3. 기본 데이터 삽입
        insert_default_business_options(engine)

        print("\n" + "=" * 50)
        print("✅ 마이그레이션 완료!")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ 마이그레이션 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
