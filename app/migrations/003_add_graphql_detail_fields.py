"""
GraphQL API 상세정보 필드 추가 마이그레이션
생성일: 2025-12-03
요구사항: REQ-DATA-004 (업체/상품 상세정보 조회)

실행 방법:
    python -m app.migrations.003_add_graphql_detail_fields

설명:
    - businesses 테이블에 위치정보, 연락처, API 동기화 시간 필드 추가
    - biz_items 테이블에 상품 상세정보, 예약 인원 범위, API 동기화 시간 필드 추가
    - SQLite는 ALTER TABLE ADD COLUMN만 지원하므로 하나씩 추가
"""

import sqlite3
import sys
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings


def get_existing_columns(cursor, table_name: str) -> set:
    """테이블의 기존 컬럼 목록 조회"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def add_column_if_not_exists(cursor, table_name: str, column_name: str, column_def: str):
    """컬럼이 없으면 추가"""
    existing = get_existing_columns(cursor, table_name)
    if column_name not in existing:
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
            print(f"  + Added: {table_name}.{column_name}")
            return True
        except sqlite3.OperationalError as e:
            print(f"  ! Error adding {table_name}.{column_name}: {e}")
            return False
    else:
        print(f"  - Exists: {table_name}.{column_name}")
        return False


def create_index_if_not_exists(cursor, index_name: str, table_name: str, column_name: str):
    """인덱스가 없으면 생성"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,)
    )
    if not cursor.fetchone():
        try:
            cursor.execute(f"CREATE INDEX {index_name} ON {table_name}({column_name})")
            print(f"  + Created index: {index_name}")
            return True
        except sqlite3.OperationalError as e:
            print(f"  ! Error creating index {index_name}: {e}")
            return False
    else:
        print(f"  - Index exists: {index_name}")
        return False


def migrate():
    """마이그레이션 실행"""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    print(f"Database: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # ============================================
        # 1. businesses 테이블 컬럼 추가
        # ============================================
        print("=== businesses 테이블 마이그레이션 ===")

        business_columns = [
            ("place_id", "TEXT"),
            ("service_name", "TEXT"),
            ("road_address", "TEXT"),
            ("jibun_address", "TEXT"),
            ("detail_address", "TEXT"),
            ("latitude", "REAL"),
            ("longitude", "REAL"),
            ("phone", "TEXT"),
            ("api_synced_at", "TIMESTAMP"),
        ]

        for col_name, col_def in business_columns:
            add_column_if_not_exists(cursor, "businesses", col_name, col_def)

        print()

        # ============================================
        # 2. biz_items 테이블 컬럼 추가
        # ============================================
        print("=== biz_items 테이블 마이그레이션 ===")

        biz_item_columns = [
            ("description", "TEXT"),
            ("biz_item_type", "TEXT"),
            ("biz_item_sub_type", "TEXT"),
            ("booking_count_type", "TEXT"),
            ("min_booking_count", "INTEGER"),
            ("max_booking_count", "INTEGER"),
            ("start_date", "TEXT"),
            ("end_date", "TEXT"),
            ("extra_desc_json", "TEXT"),
            ("booking_precaution_json", "TEXT"),
            ("api_synced_at", "TIMESTAMP"),
        ]

        for col_name, col_def in biz_item_columns:
            add_column_if_not_exists(cursor, "biz_items", col_name, col_def)

        print()

        # ============================================
        # 3. 인덱스 추가
        # ============================================
        print("=== 인덱스 생성 ===")

        indexes = [
            ("idx_businesses_latitude", "businesses", "latitude"),
            ("idx_businesses_longitude", "businesses", "longitude"),
            ("idx_businesses_api_synced_at", "businesses", "api_synced_at"),
            ("idx_biz_items_api_synced_at", "biz_items", "api_synced_at"),
        ]

        for idx_name, tbl_name, col_name in indexes:
            create_index_if_not_exists(cursor, idx_name, tbl_name, col_name)

        print()

        # 커밋
        conn.commit()
        print("=== 마이그레이션 완료 ===")

    except Exception as e:
        conn.rollback()
        print(f"마이그레이션 실패: {e}")
        raise
    finally:
        conn.close()


def verify():
    """마이그레이션 결과 검증"""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("\n=== 검증: businesses 테이블 컬럼 ===")
    cursor.execute("PRAGMA table_info(businesses)")
    for row in cursor.fetchall():
        print(f"  {row[1]}: {row[2]}")

    print("\n=== 검증: biz_items 테이블 컬럼 ===")
    cursor.execute("PRAGMA table_info(biz_items)")
    for row in cursor.fetchall():
        print(f"  {row[1]}: {row[2]}")

    conn.close()


if __name__ == "__main__":
    migrate()
    verify()
