"""
이미지 분류 전용 SQLite 데이터베이스 연결 모듈

기존 monitor-page DB와 분리하여 독립적으로 관리:
- 파일 위치: data/image_classifier.db
- 이유: 대용량 CLIP 임베딩 BLOB, 독립 백업/삭제, 스키마 충돌 방지
"""

from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 이미지 분류 DB 경로
DB_DIR = Path(__file__).resolve().parents[3] / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "image_classifier.db"
DB_URL = f"sqlite:///{DB_PATH}"

# SQLite 엔진 생성
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


# SQLite WAL 모드 및 busy_timeout 설정
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 연결 시 성능 및 동시성 설정"""
    cursor = dbapi_connection.cursor()
    # WAL 모드: 읽기/쓰기 동시 접근 허용
    cursor.execute("PRAGMA journal_mode=WAL")
    # busy_timeout: 잠금 시 30초 대기 (밀리초)
    cursor.execute("PRAGMA busy_timeout=5000")
    # synchronous=NORMAL: 성능과 안정성 균형
    cursor.execute("PRAGMA synchronous=NORMAL")
    # foreign_keys: 외래키 제약 활성화
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """의존성 주입용 DB 세션 생성"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    데이터베이스 초기화 및 마이그레이션 실행

    - 마이그레이션 파일 순차 실행
    - 멱등성 보장 (CREATE TABLE IF NOT EXISTS)
    """
    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    db = SessionLocal()
    try:
        for migration_file in migration_files:
            print(f"[이미지 분류 DB] 마이그레이션 실행: {migration_file.name}")
            sql_content = migration_file.read_text(encoding="utf-8")

            # SQL 스크립트를 세미콜론으로 분리하여 실행
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            for statement in statements:
                try:
                    db.execute(text(statement))
                except Exception as e:
                    print(f"[경고] 마이그레이션 실행 중 오류 (무시됨): {e}")

            db.commit()

        print(f"[이미지 분류 DB] 초기화 완료: {DB_PATH}")
    except Exception as e:
        db.rollback()
        print(f"[오류] 이미지 분류 DB 초기화 실패: {e}")
        raise
    finally:
        db.close()


# 모듈 임포트 시 자동 초기화 - 비활성화 (매번 불필요하게 실행됨)
# try:
#     init_db()
# except Exception as e:
#     print(f"[경고] DB 자동 초기화 실패 (무시됨): {e}")
