"""T5 HTTP: service-account 브라우저 명령 API HTTP 계약 검증

- POST /api/v1/service-accounts/{id}/browser/open  → 200 + status="pending" + open_browser
- POST /api/v1/service-accounts/{id}/browser/login → 200 + status="pending" + naver_login URL
- 404 for non-existent account_id
"""
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models.base import Base
from app.models.browser_profile import BrowserProfile
from app.models.service_account import ServiceAccount

pytestmark = pytest.mark.http

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

BROWSER_COMMANDS_DDL = """
CREATE TABLE IF NOT EXISTS browser_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,
    account_id INTEGER,
    status TEXT DEFAULT 'pending',
    request_data TEXT,
    result_data TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    service_account_id INTEGER
)
"""


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client_and_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(sa_text(BROWSER_COMMANDS_DDL))
        conn.commit()

    db = TestingSessionLocal()
    profile = BrowserProfile(name="Test Profile", profile_dir="test_profile_dir_t5")
    db.add(profile)
    db.flush()
    account = ServiceAccount(profile_id=profile.id, service_type="naver")
    db.add(account)
    db.commit()
    naver_id = account.id
    db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client, naver_id

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(sa_text("DROP TABLE IF EXISTS browser_commands"))
        conn.commit()


class TestBrowserCommandsHttpContract:
    """T5: service-account 브라우저 명령 API HTTP 계약"""

    def test_right_open_browser_returns_pending(self, client_and_db):
        """[Right] POST /browser/open → 200 + status='pending' + open_browser 삽입"""
        client, naver_id = client_and_db

        response = client.post(f"/api/v1/service-accounts/{naver_id}/browser/open")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert "command_id" in data

        db = TestingSessionLocal()
        row = db.execute(sa_text(
            "SELECT command_type, status, service_account_id FROM browser_commands WHERE id = :id"
        ), {"id": data["command_id"]}).fetchone()
        db.close()
        assert row[0] == "open_browser"
        assert row[1] == "pending"
        assert row[2] == naver_id

    def test_right_browser_login_creates_naver_login_command(self, client_and_db):
        """[Right] POST /browser/login → 200 + naver_login command + login URL"""
        client, naver_id = client_and_db

        response = client.post(f"/api/v1/service-accounts/{naver_id}/browser/login")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"

        db = TestingSessionLocal()
        row = db.execute(sa_text(
            "SELECT command_type, request_data FROM browser_commands WHERE id = :id"
        ), {"id": data["command_id"]}).fetchone()
        db.close()
        assert row[0] == "naver_login"
        request_data = json.loads(row[1])
        assert request_data["url"] == "https://nid.naver.com/nidlogin.login"

    def test_error_nonexistent_account_open_returns_404(self, client_and_db):
        """[Error] 존재하지 않는 account_id → 404 (open)"""
        client, _ = client_and_db

        response = client.post("/api/v1/service-accounts/99999/browser/open")
        assert response.status_code == 404

    def test_error_nonexistent_account_login_returns_404(self, client_and_db):
        """[Error] 존재하지 않는 account_id → 404 (login)"""
        client, _ = client_and_db

        response = client.post("/api/v1/service-accounts/99999/browser/login")
        assert response.status_code == 404
