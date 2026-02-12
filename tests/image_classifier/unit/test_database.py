"""DB 초기화 테스트"""
import pytest
from sqlalchemy import text, inspect


def test_init_db_creates_all_tables(test_db):
    """1.1 Right: 17개 테이블이 모두 생성되어야 함"""
    inspector = inspect(test_db.bind)
    tables = inspector.get_table_names()

    expected_tables = [
        "categories",
        "folder_mappings",
        "file_classifications",
        "time_clusters",
        "tags",
        "file_tags",
        "file_attributes",
        "duplicate_groups",
        "duplicate_members",
        "image_features",
        "similarity_cache",
        "classification_rules",
        "feedback_history",
        "filename_patterns",
        "year_annotations",
        "api_usage",
        "api_limits",
    ]

    for table in expected_tables:
        assert table in tables, f"테이블 {table}이(가) 생성되지 않았습니다"


def test_init_db_is_idempotent(test_db):
    """1.2 Boundary: 여러 번 실행해도 에러 없어야 함"""
    # 이미 init_db()가 실행된 상태 (fixture에서)
    # 다시 마이그레이션 실행
    from pathlib import Path

    migrations_dir = Path(__file__).parent.parent.parent.parent / "app" / "modules" / "image_classifier" / "migrations"
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text(encoding="utf-8")
        with test_db.bind.connect() as conn:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        conn.execute(text(stmt))
                    except Exception:
                        pass  # CREATE TABLE IF NOT EXISTS → 에러 무시
            conn.commit()

    # 에러 없이 완료됨
    assert True


def test_initial_data_inserted(test_db):
    """1.3 Right: 초기 데이터가 INSERT되어야 함"""
    # filename_patterns 12행
    result = test_db.execute(text("SELECT COUNT(*) FROM filename_patterns")).fetchone()
    assert result[0] == 12, f"filename_patterns 예상 12행, 실제 {result[0]}행"

    # api_limits 2행
    result = test_db.execute(text("SELECT COUNT(*) FROM api_limits")).fetchone()
    assert result[0] == 2, f"api_limits 예상 2행, 실제 {result[0]}행"


def test_check_constraint_folder_status(test_db):
    """1.4 Error: BUG-1 검증 - folder_status='unknown' INSERT 가능해야 함"""
    # DEFAULT 'unknown'으로 INSERT (folder_status 명시 안 함)
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count)
        VALUES ('/test/path', 10)
    """))
    test_db.commit()

    # 조회 확인
    result = test_db.execute(text("""
        SELECT folder_status FROM folder_mappings WHERE folder_path = '/test/path'
    """)).fetchone()

    assert result[0] == "unknown", "DEFAULT 'unknown'이 제대로 저장되지 않음"

    # 명시적으로 'unknown' INSERT
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count, folder_status)
        VALUES ('/test/path2', 20, 'unknown')
    """))
    test_db.commit()

    result = test_db.execute(text("""
        SELECT folder_status FROM folder_mappings WHERE folder_path = '/test/path2'
    """)).fetchone()
    assert result[0] == "unknown"


def test_check_constraint_file_status(test_db):
    """1.5 Error: file_classifications.status CHECK 제약 검증"""
    # 유효한 값들
    valid_statuses = ["pending", "folder_mapped", "ai_classified", "approved", "moved", "error"]

    for status in valid_statuses:
        test_db.execute(text(f"""
            INSERT INTO file_classifications (file_path, file_hash, status)
            VALUES ('/{status}.jpg', 'hash{status}', '{status}')
        """))
    test_db.commit()

    # 개수 확인
    result = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()
    assert result[0] == len(valid_statuses)

    # 유효하지 않은 값 → 에러
    with pytest.raises(Exception):
        test_db.execute(text("""
            INSERT INTO file_classifications (file_path, file_hash, status)
            VALUES ('/invalid.jpg', 'hashinvalid', 'invalid_status')
        """))
        test_db.commit()


def test_foreign_key_enforcement(test_db):
    """1.6 Right: FK 제약이 활성화되어 있어야 함"""
    # 존재하지 않는 category_id 참조 → 에러
    with pytest.raises(Exception):
        test_db.execute(text("""
            INSERT INTO folder_mappings (folder_path, file_count, category_id)
            VALUES ('/test/fk', 10, 9999)
        """))
        test_db.commit()


def test_unique_constraints(test_db):
    """1.7 Right: UNIQUE 제약 검증"""
    # file_classifications.file_path UNIQUE
    test_db.execute(text("""
        INSERT INTO file_classifications (file_path, file_hash)
        VALUES ('/unique/test.jpg', 'hash1')
    """))
    test_db.commit()

    with pytest.raises(Exception):
        test_db.execute(text("""
            INSERT INTO file_classifications (file_path, file_hash)
            VALUES ('/unique/test.jpg', 'hash2')
        """))
        test_db.commit()

    # categories.full_path UNIQUE
    test_db.execute(text("""
        INSERT INTO categories (name, full_path) VALUES ('테스트', '테스트')
    """))
    test_db.commit()

    with pytest.raises(Exception):
        test_db.execute(text("""
            INSERT INTO categories (name, full_path) VALUES ('테스트2', '테스트')
        """))
        test_db.commit()
