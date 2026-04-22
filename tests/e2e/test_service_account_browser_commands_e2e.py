"""T4(integration): service-account 브라우저 명령 API → NaverMonitorWorker 소비 통합 검증

- POST /browser/open → pending command → _process_browser_commands() → completed
- execute_with_tab 1회만 호출됨
- 3회 연속 enqueue → sequential 처리, 각 명령 completed
"""
import pytest
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.browser_profile import BrowserProfile
from app.models.service_account import ServiceAccount

pytestmark = pytest.mark.integration

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SETUP_DDL = [
    """CREATE TABLE IF NOT EXISTS browser_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        profile_dir TEXT NOT NULL UNIQUE,
        is_active INTEGER DEFAULT 1,
        description TEXT,
        last_used_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS service_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER NOT NULL REFERENCES browser_profiles(id) ON DELETE CASCADE,
        service_type TEXT NOT NULL,
        username TEXT,
        password TEXT,
        is_logged_in INTEGER DEFAULT 0,
        last_login_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS browser_commands (
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
    )""",
]


@pytest.fixture(scope="module")
def worker_db():
    with engine.connect() as conn:
        for ddl in SETUP_DDL:
            conn.execute(sa_text(ddl))
        conn.commit()

    db = TestingSessionLocal()
    db.execute(sa_text(
        "INSERT INTO browser_profiles (name, profile_dir) VALUES ('E2E Integration Profile', 'test_profile_dir_e2e')"
    ))
    db.commit()
    profile_id = db.execute(sa_text("SELECT last_insert_rowid()")).scalar()
    db.execute(sa_text(
        "INSERT INTO service_accounts (profile_id, service_type) VALUES (:pid, 'naver')"
    ), {"pid": profile_id})
    db.commit()
    naver_id = db.execute(sa_text("SELECT last_insert_rowid()")).scalar()
    db.close()

    yield naver_id

    with engine.connect() as conn:
        conn.execute(sa_text("DROP TABLE IF EXISTS browser_commands"))
        conn.execute(sa_text("DROP TABLE IF EXISTS service_accounts"))
        conn.execute(sa_text("DROP TABLE IF EXISTS browser_profiles"))
        conn.commit()


def _insert_pending(Session, naver_id: int, command_type: str) -> int:
    db = Session()
    db.execute(sa_text("""
        INSERT INTO browser_commands (command_type, service_account_id, status)
        VALUES (:ct, :sid, 'pending')
    """), {"ct": command_type, "sid": naver_id})
    db.commit()
    cmd_id = db.execute(sa_text("SELECT last_insert_rowid()")).scalar()
    db.close()
    return cmd_id


def _make_worker(execute_mock=None):
    from app.worker.naver_monitor_worker import NaverMonitorWorker

    mock_browser = MagicMock()
    mock_browser.is_initialized = True
    mock_browser.execute_with_tab = execute_mock or AsyncMock(return_value=None)
    mock_browser.tab_pool_manager = MagicMock()

    worker = NaverMonitorWorker(mock_browser)
    worker.browser = mock_browser
    return worker


class TestBrowserCommandE2EFlow:
    """T4(integration): API enqueue → worker consumption flow"""

    @pytest.mark.asyncio
    async def test_right_open_browser_command_completes(self, worker_db):
        """[Right] open_browser 명령이 _process_browser_commands() 처리 후 completed로 전이"""
        naver_id = worker_db
        execute_mock = AsyncMock(return_value=None)
        worker = _make_worker(execute_mock)

        cmd_id = _insert_pending(TestingSessionLocal, naver_id, "open_browser")

        with patch("app.worker.naver_monitor_worker.SessionLocal", TestingSessionLocal):
            await worker._process_browser_commands()

        db = TestingSessionLocal()
        row = db.execute(sa_text(
            "SELECT status FROM browser_commands WHERE id = :id"
        ), {"id": cmd_id}).fetchone()
        db.close()

        assert row[0] == "completed", f"Expected completed, got {row[0]}"
        execute_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_boundary_execute_with_tab_called_once_per_command(self, worker_db):
        """[Boundary] 명령 1개 처리 시 execute_with_tab 정확히 1회 호출"""
        naver_id = worker_db
        execute_mock = AsyncMock(return_value=None)
        worker = _make_worker(execute_mock)

        _insert_pending(TestingSessionLocal, naver_id, "naver_login")

        with patch("app.worker.naver_monitor_worker.SessionLocal", TestingSessionLocal):
            await worker._process_browser_commands()

        assert execute_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_right_three_sequential_enqueues_all_completed(self, worker_db):
        """[Right] 3회 연속 enqueue → _process_browser_commands 1회 실행으로 3개 모두 completed"""
        naver_id = worker_db
        execute_mock = AsyncMock(return_value=None)
        worker = _make_worker(execute_mock)

        ids = [_insert_pending(TestingSessionLocal, naver_id, "open_browser") for _ in range(3)]

        with patch("app.worker.naver_monitor_worker.SessionLocal", TestingSessionLocal):
            await worker._process_browser_commands()

        db = TestingSessionLocal()
        statuses = [
            db.execute(sa_text("SELECT status FROM browser_commands WHERE id = :id"), {"id": i}).scalar()
            for i in ids
        ]
        db.close()

        assert all(s == "completed" for s in statuses), f"Expected all completed, got {statuses}"
        assert execute_mock.call_count == 3
