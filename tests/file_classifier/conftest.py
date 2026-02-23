"""파일 분류기 테스트 공통 fixtures"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ================================================
# DB Fixtures
# ================================================

@pytest.fixture(scope="function")
def test_db(tmp_path):
    """각 테스트마다 독립된 SQLite DB 생성"""
    db_path = tmp_path / "test_file_classifier.db"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Session = sessionmaker(bind=engine)

    # 마이그레이션 실행
    migrations_dir = (
        Path(__file__).parent.parent.parent
        / "app" / "modules" / "file_classifier" / "migrations"
    )
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text(encoding="utf-8")
        with engine.connect() as conn:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        conn.execute(text(stmt))
                    except Exception:
                        pass
            conn.commit()

    db = Session()
    yield db
    db.close()
    engine.dispose()


@pytest.fixture
def seeded_db(test_db):
    """fc_files가 일부 채워진 DB"""
    test_db.execute(
        text("""
            INSERT INTO fc_files (file_path, file_name, extension, file_size, file_group)
            VALUES
                ('C:/Music/song.mp3', 'song.mp3', '.mp3', 5242880, 'music'),
                ('C:/Downloads/archive.zip', 'archive.zip', '.zip', 10485760, 'archive'),
                ('C:/Docs/report.pdf', 'report.pdf', '.pdf', 1048576, 'document'),
                ('C:/Software/setup.exe', 'setup.exe', '.exe', 52428800, 'installer'),
                ('C:/Games/chart.dtx', 'chart.dtx', '.dtx', 102400, 'game'),
                ('C:/Misc/unknown.dat', 'unknown.dat', '.dat', 1024, 'misc')
        """)
    )
    test_db.commit()
    return test_db


@pytest.fixture
def client(test_db):
    """테스트용 FastAPI TestClient (file_classifier DB를 test_db로 교체)"""
    from fastapi import FastAPI
    from app.modules.file_classifier.routers.health import router as health_router
    from app.modules.file_classifier.routers.scan import router as scan_router
    from app.modules.file_classifier.routers.files import router as files_router
    from app.modules.file_classifier.routers.stats import router as stats_router
    from app.modules.file_classifier.database import get_db

    app = FastAPI()
    app.include_router(health_router, prefix="/api/fc")
    app.include_router(scan_router, prefix="/api/fc")
    app.include_router(files_router, prefix="/api/fc")
    app.include_router(stats_router, prefix="/api/fc")

    # DB 의존성 오버라이드
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_client(seeded_db):
    """시드 데이터가 있는 TestClient"""
    from fastapi import FastAPI
    from app.modules.file_classifier.routers.health import router as health_router
    from app.modules.file_classifier.routers.scan import router as scan_router
    from app.modules.file_classifier.routers.files import router as files_router
    from app.modules.file_classifier.routers.stats import router as stats_router
    from app.modules.file_classifier.database import get_db

    app = FastAPI()
    app.include_router(health_router, prefix="/api/fc")
    app.include_router(scan_router, prefix="/api/fc")
    app.include_router(files_router, prefix="/api/fc")
    app.include_router(stats_router, prefix="/api/fc")

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c
