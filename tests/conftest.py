"""
pytest 설정 및 공통 픽스처

Windows에서 한글 출력 시 인코딩 문제 해결을 위한 설정 포함
테스트 DB 자동 생성 및 마이그레이션 적용 포함
"""

import sys
import os
import re
import sqlite3
import shutil
import io

# Windows에서 UTF-8 인코딩 강제 설정 (가장 먼저 실행)
if sys.platform == 'win32':
    # 환경 변수 설정 (다른 프로세스에도 영향)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

    # stdout/stderr를 UTF-8로 설정
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')


import pytest


from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 테스트 DB 경로
TEST_DB_PATH = PROJECT_ROOT / "data" / "test_monitor.db"
MIGRATIONS_DIR = PROJECT_ROOT / "app" / "migrations"


def get_migration_number(filename: str) -> int:
    """마이그레이션 파일 번호 추출 (예: 001_xxx.sql -> 1)"""
    match = re.match(r'^(\d+)', filename)
    return int(match.group(1)) if match else 999


def apply_migrations(db_path: Path) -> None:
    """마이그레이션 파일들을 순서대로 적용"""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 마이그레이션 파일 정렬 (번호순)
    migration_files = sorted(
        MIGRATIONS_DIR.glob("*.sql"),
        key=lambda f: (get_migration_number(f.name), f.name)
    )

    for sql_file in migration_files:
        try:
            sql_content = sql_file.read_text(encoding='utf-8')
            # 여러 문장으로 분리하여 실행
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            for stmt in statements:
                try:
                    cursor.execute(stmt)
                except sqlite3.OperationalError as e:
                    # 이미 존재하는 테이블/컬럼 등은 무시
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        pass
                    else:
                        # 다른 에러도 무시 (테스트 DB이므로)
                        pass
        except Exception as e:
            # 파일 읽기 실패 등은 무시
            pass

    conn.commit()
    conn.close()


@pytest.fixture(scope="session")
def test_db_engine():
    """
    마이그레이션이 적용된 테스트 DB 엔진 (세션 범위)

    모든 테스트에서 공유되는 테스트 전용 DB를 생성하고 마이그레이션을 적용합니다.
    테스트 세션 종료 시 자동으로 정리됩니다.
    """
    from app.database import Base

    # 기존 테스트 DB 삭제
    if TEST_DB_PATH.exists():
        try:
            os.remove(TEST_DB_PATH)
        except PermissionError:
            pass

    # 테스트 DB 엔진 생성
    engine = create_engine(
        f"sqlite:///{TEST_DB_PATH}",
        connect_args={"check_same_thread": False}
    )

    # 1. SQLAlchemy 모델로 기본 테이블 생성
    Base.metadata.create_all(bind=engine)

    # 2. 마이그레이션 적용 (추가 컬럼, 인덱스 등)
    apply_migrations(TEST_DB_PATH)

    yield engine

    # 정리
    engine.dispose()
    try:
        if TEST_DB_PATH.exists():
            os.remove(TEST_DB_PATH)
    except PermissionError:
        pass


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    """
    테스트용 DB 세션 (함수 범위)

    각 테스트 함수마다 새로운 세션을 제공하고,
    테스트 종료 시 롤백하여 격리를 보장합니다.
    """
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    session = Session()

    yield session

    session.rollback()
    session.close()


@pytest.fixture
def mock_external_request():
    """
    외부 요청을 시뮬레이션하는 fixture

    is_localhost_request가 False를 반환하도록 mock하여
    외부 IP에서의 요청처럼 동작하게 합니다.

    여러 모듈에서 import된 함수를 모두 mock해야 합니다.
    """
    from unittest.mock import patch

    with patch('app.core.auth.is_localhost_request', return_value=False), \
         patch('app.routes.auth.is_localhost_request', return_value=False):
        yield
