"""
PostgreSQL 연결 독립 테스트 스크립트.
앱 코드와 무관하게 PG 설치 + 연결 정상 여부를 확인한다.
"""
import sys

PG_URL = "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor"


def test_psycopg2_direct():
    """psycopg2 직접 연결 확인"""
    import psycopg2
    conn = psycopg2.connect(
        dbname="monitor",
        user="monitor_user",
        password="monitor_pass_2026",
        host="localhost",
        port=5432,
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"  [PASS] psycopg2 직접 연결: {version[:50]}")


def test_sqlalchemy_engine():
    """SQLAlchemy create_engine으로 PG 엔진 생성 확인"""
    from sqlalchemy import create_engine, text
    engine = create_engine(PG_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), current_user;"))
        db, user = result.fetchone()
    engine.dispose()
    print(f"  [PASS] SQLAlchemy 엔진: db={db}, user={user}")


def test_crud_round_trip():
    """CREATE TABLE → INSERT → SELECT → DROP 왕복 확인"""
    from sqlalchemy import create_engine, text
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS _pg_conn_test "
            "(id SERIAL PRIMARY KEY, val TEXT NOT NULL)"
        ))
        conn.execute(text("INSERT INTO _pg_conn_test (val) VALUES (:v)"), {"v": "hello"})
        result = conn.execute(text("SELECT val FROM _pg_conn_test LIMIT 1")).fetchone()
        assert result[0] == "hello", f"Expected 'hello', got {result[0]}"
        conn.execute(text("DROP TABLE _pg_conn_test"))
    engine.dispose()
    print("  [PASS] CRUD 왕복: CREATE → INSERT → SELECT → DROP 성공")


def main():
    print("=== PostgreSQL 연결 테스트 ===")
    tests = [
        ("psycopg2 직접 연결", test_psycopg2_direct),
        ("SQLAlchemy 엔진", test_sqlalchemy_engine),
        ("CRUD 왕복", test_crud_round_trip),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print(f"\n결과: {len(tests) - failed}/{len(tests)} 통과")
    if failed:
        sys.exit(1)
    print("모든 테스트 통과 - PostgreSQL 연결 정상")


if __name__ == "__main__":
    main()
