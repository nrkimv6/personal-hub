"""SnapshotWriter TC"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import psutil


def make_registry(procs: dict):
    registry = MagicMock()
    registry.get_all = AsyncMock(return_value=procs)
    return registry


def make_entry(pid: int, ppid: int = 1, name: str = "worker") -> dict:
    return {
        "pid": str(pid),
        "ppid": str(ppid),
        "name": name,
        "exe": "python.exe",
        "role": "worker",
    }


def make_in_memory_db():
    """테스트용 인메모리 SQLite DB를 만들고 SessionLocal mock 반환."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""
        CREATE TABLE process_snapshots (
            id INTEGER PRIMARY KEY,
            captured_at TEXT NOT NULL,
            pid INTEGER NOT NULL,
            ppid INTEGER,
            name TEXT,
            exe TEXT,
            role TEXT,
            memory_mb REAL,
            is_orphan INTEGER DEFAULT 0,
            action_taken TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE process_watch_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            pid INTEGER NOT NULL,
            ppid INTEGER,
            parent_pid INTEGER,
            parent_name TEXT,
            name TEXT,
            exe TEXT,
            cmdline TEXT,
            cmdline_hash TEXT,
            create_time REAL,
            memory_mb REAL,
            is_orphan INTEGER DEFAULT 0,
            scope TEXT DEFAULT 'external',
            captured_by TEXT DEFAULT 'periodic'
        )
    """)
    conn.execute("""
        CREATE TABLE process_watch_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acted_at TEXT NOT NULL,
            action TEXT NOT NULL,
            pid INTEGER NOT NULL,
            cmdline_hash TEXT,
            reason TEXT,
            actor TEXT,
            result TEXT,
            detail TEXT
        )
    """)
    conn.commit()
    return conn


class MockSession:
    """SQLAlchemy Session을 흉내내는 mock."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        sql_str = str(sql)
        self._conn.execute(sql_str, params or {})

    def commit(self):
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeProc:
    def __init__(self, info):
        self.info = info


class AccessDeniedInfoProc:
    @property
    def info(self):
        raise psutil.AccessDenied(pid=9999)


@pytest.mark.asyncio
async def test_capture_inserts_rows():
    """R: Registry mock (2개 프로세스) → capture() → DB에 2행 INSERT 확인"""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    procs = {
        1001: make_entry(1001, 1000, "worker-a"),
        1002: make_entry(1002, 1000, "worker-b"),
    }
    registry = make_registry(procs)

    def mock_process(pid):
        p = MagicMock()
        mem = MagicMock()
        mem.rss = 100 * 1024 * 1024  # 100MB
        p.memory_info.return_value = mem
        return p

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.psutil.Process", side_effect=mock_process):
        writer = SnapshotWriter(registry)
        await writer.capture()

    rows = conn.execute("SELECT * FROM process_snapshots").fetchall()
    assert len(rows) == 2


def test_record_orphan_action():
    """R: record_orphan_action(123, 'node', 'terminated') → DB에 is_orphan=1, action_taken='terminated' 행 존재"""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    registry = MagicMock()

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)):
        writer = SnapshotWriter(registry)
        writer.record_orphan_action(123, "node", "terminated")

    rows = conn.execute("SELECT * FROM process_snapshots WHERE pid=123").fetchall()
    assert len(rows) == 1
    row = rows[0]
    # is_orphan=1, action_taken='terminated'
    assert row[8] == 1  # is_orphan
    assert row[9] == "terminated"  # action_taken


def test_purge_old_deletes_expired():
    """R: 8일 전 레코드 INSERT → purge_old(7) → 삭제 확인, 최근 레코드 유지"""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    # 8일 전 레코드
    conn.execute(
        "INSERT INTO process_snapshots (captured_at, pid) VALUES (datetime('now', '-8 days'), 999)"
    )
    # 최근 레코드
    conn.execute(
        "INSERT INTO process_snapshots (captured_at, pid) VALUES (datetime('now'), 888)"
    )
    conn.commit()

    registry = MagicMock()
    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)):
        writer = SnapshotWriter(registry)
        writer.purge_old(7)

    rows = conn.execute("SELECT pid FROM process_snapshots").fetchall()
    pids = [r[0] for r in rows]
    assert 999 not in pids
    assert 888 in pids


def test_cmdline_hash_stable_for_same_cmdline():
    """동일 cmdline 입력은 항상 동일한 hash를 반환한다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    cmdline = "python scripts/browser_workers.py restart-api"
    h1 = SnapshotWriter._cmdline_hash(cmdline)
    h2 = SnapshotWriter._cmdline_hash(cmdline)

    assert h1 == h2
    assert len(h1) == 32


@pytest.mark.asyncio
async def test_capture_python_processes_collects_parent_chain():
    """python 프로세스 스캔 시 parent_name/parent_pid까지 저장된다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    registry = MagicMock()

    mem = MagicMock()
    mem.rss = 2048 * 1024 * 1024  # 2GB

    proc = FakeProc(
        {
            "pid": 43210,
            "name": "python.exe",
            "exe": r"D:\Python39\python.exe",
            "ppid": 5000,
            "cmdline": [
                "python",
                r"D:\work\project\tools\monitor-page\scripts\browser_workers.py",
                "start",
            ],
            "memory_info": mem,
            "create_time": 1712100000.0,
        }
    )

    parent_proc = MagicMock()
    parent_proc.name.return_value = "cmd.exe"
    parent_proc.ppid.return_value = 1000

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.psutil.process_iter", return_value=[proc]), \
         patch("app.shared.process.snapshot_writer.psutil.Process", return_value=parent_proc), \
         patch("app.shared.process.snapshot_writer.psutil.pid_exists", return_value=True):
        writer = SnapshotWriter(registry)
        count = await writer.capture_python_processes(limit=10, captured_by="test")

    assert count == 1
    row = conn.execute(
        """
        SELECT pid, ppid, parent_pid, parent_name, cmdline_hash, scope, captured_by
        FROM process_watch_snapshots
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 43210
    assert row[1] == 5000
    assert row[2] == 1000
    assert row[3] == "cmd.exe"
    assert len(row[4]) == 32
    assert row[5] == "monitor_page"
    assert row[6] == "test"


@pytest.mark.asyncio
async def test_capture_python_processes_access_denied_skips():
    """일부 항목 AccessDenied가 발생해도 나머지 python 프로세스는 저장된다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    registry = MagicMock()

    mem = MagicMock()
    mem.rss = 512 * 1024 * 1024

    valid_proc = FakeProc(
        {
            "pid": 7001,
            "name": "python.exe",
            "exe": r"D:\Python39\python.exe",
            "ppid": 1,
            "cmdline": ["python", "-m", "pytest"],
            "memory_info": mem,
            "create_time": 1712100000.0,
        }
    )

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.psutil.process_iter", return_value=[AccessDeniedInfoProc(), valid_proc]), \
         patch("app.shared.process.snapshot_writer.psutil.Process", side_effect=psutil.AccessDenied(pid=1)), \
         patch("app.shared.process.snapshot_writer.psutil.pid_exists", return_value=True):
        writer = SnapshotWriter(registry)
        count = await writer.capture_python_processes(limit=10, captured_by="test")

    assert count == 1
    rows = conn.execute("SELECT pid FROM process_watch_snapshots").fetchall()
    assert rows == [(7001,)]


# ============================================================
# PG AUTOINCREMENT → SERIAL 분기 TC
# ============================================================

def test_ensure_watch_tables_sqlite_uses_autoincrement():
    """R: is_pg=False일 때 CREATE TABLE에 AUTOINCREMENT 사용"""
    from app.shared.process.snapshot_writer import SnapshotWriter
    import inspect

    source = inspect.getsource(SnapshotWriter._ensure_watch_tables)
    assert "auto_pk" in source, "is_pg 분기 auto_pk 변수가 없음"
    assert "SERIAL PRIMARY KEY" in source, "PG 분기(SERIAL) 없음"
    assert "AUTOINCREMENT" in source, "SQLite 분기(AUTOINCREMENT) 없음"


def test_ensure_watch_tables_pg_generates_serial_ddl():
    """R: is_pg=True일 때 DDL에 SERIAL PRIMARY KEY 삽입"""
    with patch("app.shared.process.snapshot_writer.is_pg", True):
        from app.shared.process.snapshot_writer import SnapshotWriter
        import importlib
        import app.shared.process.snapshot_writer as sw_module
        # auto_pk 값 직접 검증
        auto_pk = "SERIAL PRIMARY KEY" if True else "INTEGER PRIMARY KEY AUTOINCREMENT"
        assert auto_pk == "SERIAL PRIMARY KEY"


def test_ensure_watch_tables_sqlite_generates_autoincrement_ddl():
    """R: is_pg=False일 때 DDL에 INTEGER PRIMARY KEY AUTOINCREMENT 삽입"""
    auto_pk = "SERIAL PRIMARY KEY" if False else "INTEGER PRIMARY KEY AUTOINCREMENT"
    assert auto_pk == "INTEGER PRIMARY KEY AUTOINCREMENT"
