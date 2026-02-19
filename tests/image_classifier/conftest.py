"""공통 pytest fixtures"""
import os
import sys
import pytest
import tempfile
from pathlib import Path
from sqlalchemy import create_engine, text
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
    db_path = tmp_path / "test_image_classifier.db"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    # SQLite FK 제약 활성화
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Session = sessionmaker(bind=engine)

    # 마이그레이션 실행
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "modules" / "image_classifier" / "migrations"
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text(encoding="utf-8")
        with engine.connect() as conn:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.commit()

    db = Session()
    yield db
    db.close()
    engine.dispose()


@pytest.fixture
def seeded_db(test_db):
    """카테고리/폴더/파일이 미리 채워진 DB"""
    # 카테고리
    test_db.execute(text("""
        INSERT INTO categories (name, full_path) VALUES
        ('여행', '여행'), ('음식', '음식'), ('가족', '가족')
    """))

    # 폴더
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count, folder_status) VALUES
        ('D:/Photos/여행', 50, 'unknown'),
        ('D:/Photos/새 폴더', 30, 'unknown'),
        ('D:/Photos/20230415', 10, 'unknown')
    """))

    # 파일
    test_db.execute(text("""
        INSERT INTO file_classifications (file_path, file_hash, source_folder_id, status) VALUES
        ('D:/Photos/여행/IMG_001.jpg', 'abc123', 1, 'pending'),
        ('D:/Photos/새 폴더/photo.jpg', 'def456', 2, 'pending')
    """))
    test_db.commit()
    yield test_db


# ================================================
# FastAPI TestClient
# ================================================

@pytest.fixture(scope="function")
def client(test_db, monkeypatch):
    """FastAPI TestClient (테스트 DB 주입)"""
    from unittest.mock import MagicMock, AsyncMock

    # NotificationService mock (lifespan에서 실제 DB 연결 방지)
    mock_notif = MagicMock()
    mock_notif.should_notify.return_value = False
    mock_notif.send_notification_message = AsyncMock()
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService",
        lambda *a, **kw: mock_notif,
    )
    monkeypatch.setattr(
        "app.shared.notification.notification_service.NotificationService",
        lambda *a, **kw: mock_notif,
    )

    from app.modules.image_classifier.database import get_db
    from app.main import app

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ================================================
# 이미지 Fixtures
# ================================================

@pytest.fixture
def sample_jpg(tmp_path):
    """EXIF 포함 JPEG 이미지 생성"""
    from PIL import Image
    import piexif

    img = Image.new("RGB", (1920, 1080), color=(100, 150, 200))
    exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2023:04:15 12:30:45"}}
    exif_bytes = piexif.dump(exif_dict)

    path = tmp_path / "IMG_20230415_123045.jpg"
    img.save(str(path), exif=exif_bytes, quality=85)
    return path


@pytest.fixture
def sample_png(tmp_path):
    """EXIF 없는 PNG 이미지"""
    from PIL import Image

    img = Image.new("RGBA", (800, 600), color=(255, 0, 0, 128))
    path = tmp_path / "screenshot.png"
    img.save(str(path))
    return path


@pytest.fixture
def duplicate_pair(tmp_path):
    """pHash가 유사한 이미지 쌍"""
    from PIL import Image

    img_a = Image.new("RGB", (1000, 1000), color=(50, 100, 150))
    path_a = tmp_path / "dup_a.jpg"
    img_a.save(str(path_a), quality=95)

    # 약간 변형 (리사이즈)
    img_b = img_a.resize((999, 999))
    path_b = tmp_path / "dup_b.jpg"
    img_b.save(str(path_b), quality=90)

    return path_a, path_b


@pytest.fixture
def folder_structure(tmp_path):
    """다양한 폴더 구조 생성"""
    from PIL import Image

    img = Image.new("RGB", (100, 100), color="red")

    # clear 폴더
    clear = tmp_path / "여행 2023"
    clear.mkdir()
    img.save(str(clear / "photo1.jpg"))
    img.save(str(clear / "photo2.jpg"))

    # unclear 폴더
    unclear = tmp_path / "새 폴더"
    unclear.mkdir()
    img.save(str(unclear / "a.jpg"))

    # nested 폴더
    nested = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
    nested.mkdir(parents=True)
    img.save(str(nested / "deep.jpg"))

    # flat 폴더 (파일 500개 이상)
    flat_dir = tmp_path / "dumps"
    flat_dir.mkdir()
    for i in range(501):
        (flat_dir / f"img_{i:04d}.jpg").touch()

    return tmp_path


# ================================================
# Settings Fixtures
# ================================================

@pytest.fixture
def temp_settings_file(tmp_path):
    """임시 설정 파일 경로"""
    return tmp_path / "settings.json"
