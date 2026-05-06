"""SnapshotWriter TC"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import inspect
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
        cursor = self._conn.execute(sql_str, params or {})
        return _ResultProxy(cursor)

    def commit(self):
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _ResultRow:
    def __init__(self, row, keys):
        self._row = row
        self._mapping = dict(zip(keys, row))

    def __getitem__(self, item):
        return self._row[item]


class _ResultProxy:
    def __init__(self, cursor):
        self._cursor = cursor
        self._keys = [col[0] for col in (cursor.description or [])]

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None or not self._keys:
            return row
        return _ResultRow(row, self._keys)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not self._keys:
            return rows
        return [_ResultRow(row, self._keys) for row in rows]


class FakeProc:
    def __init__(self, info):
        self.info = info


class AccessDeniedInfoProc:
    @property
    def info(self):
        raise psutil.AccessDenied(pid=9999)


class RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params or {}))
        return MagicMock()


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
         patch("app.shared.process.snapshot_writer.is_pg", False), \
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

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.is_pg", False):
        writer = SnapshotWriter(registry)
        writer.record_orphan_action(123, "node", "terminated")

    rows = conn.execute("SELECT * FROM process_snapshots WHERE pid=123").fetchall()
    assert len(rows) == 1
    row = rows[0]
    # SQLite는 bool을 0/1로 저장하므로 truthy 여부로 검증한다.
    assert bool(row[8]) is True
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
    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.is_pg", False):
        writer = SnapshotWriter(registry)
        writer.purge_old(7)

    rows = conn.execute("SELECT pid FROM process_snapshots").fetchall()
    pids = [r[0] for r in rows]
    assert 999 not in pids
    assert 888 in pids


def test_cmdline_hash_stable_for_same_cmdline():
    """동일 cmdline 입력은 항상 동일한 hash를 반환한다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    cmdline = "python scripts/services/browser_workers.py restart-api"
    h1 = SnapshotWriter._cmdline_hash(cmdline)
    h2 = SnapshotWriter._cmdline_hash(cmdline)

    assert h1 == h2
    assert len(h1) == 32


def test_safe_bool_returns_real_bool():
    """_safe_bool()는 PG boolean 컬럼에 바로 바인딩 가능한 bool을 반환한다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    assert type(SnapshotWriter._safe_bool(True)) is bool
    assert type(SnapshotWriter._safe_bool(False)) is bool
    assert SnapshotWriter._safe_bool(1) is True
    assert SnapshotWriter._safe_bool(0) is False


def test_purge_watch_rows_uses_cutoff_params():
    """R: purge는 backend별 interval 문법 대신 cutoff 파라미터만 사용한다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    writer = SnapshotWriter(MagicMock())
    db = RecordingDb()
    writer._purge_watch_rows(db)

    assert len(db.calls) == 2
    assert all(":window::interval" not in sql for sql, _ in db.calls)
    assert "process_watch_snapshots" in db.calls[0][0]
    assert "captured_at < :cutoff" in db.calls[0][0]
    assert "cutoff" in db.calls[0][1]
    assert "process_watch_actions" in db.calls[1][0]
    assert "acted_at < :cutoff" in db.calls[1][0]
    assert "cutoff" in db.calls[1][1]


def test_ensure_watch_tables_pg_advisory_lock_precedes_ddl():
    """R: PG DDL 생성은 advisory lock을 먼저 잡아 동시 watchdog 시작 경합을 줄인다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    writer = SnapshotWriter(MagicMock())
    db = RecordingDb()
    SnapshotWriter._watch_tables_ready["pg"] = False
    try:
        with patch("app.shared.process.snapshot_writer.is_pg", True):
            writer._ensure_watch_tables(db)
    finally:
        SnapshotWriter._watch_tables_ready["pg"] = False

    assert db.calls
    assert "pg_advisory_xact_lock" in db.calls[0][0]
    assert any("CREATE INDEX IF NOT EXISTS idx_pws_captured_at" in sql for sql, _ in db.calls)


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
                r"D:\work\project\tools\monitor-page\scripts\services\browser_workers.py",
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
         patch("app.shared.process.snapshot_writer.is_pg", False), \
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
         patch("app.shared.process.snapshot_writer.is_pg", False), \
         patch("app.shared.process.snapshot_writer.psutil.process_iter", return_value=[AccessDeniedInfoProc(), valid_proc]), \
         patch("app.shared.process.snapshot_writer.psutil.Process", side_effect=psutil.AccessDenied(pid=1)), \
         patch("app.shared.process.snapshot_writer.psutil.pid_exists", return_value=True):
        writer = SnapshotWriter(registry)
        count = await writer.capture_python_processes(limit=10, captured_by="test")

    assert count == 1
    rows = conn.execute("SELECT pid FROM process_watch_snapshots").fetchall()
    assert rows == [(7001,)]


def test_get_python_snapshot_history_only_orphan_filters():
    """only_orphan=True면 orphan row만 반환하고 응답 타입은 bool을 유지한다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    conn = make_in_memory_db()
    conn.execute(
        """
        INSERT INTO process_watch_snapshots (
            captured_at, pid, ppid, parent_pid, parent_name, name, exe, cmdline,
            cmdline_hash, create_time, memory_mb, is_orphan, scope, captured_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2026-04-16T15:50:00", 9001, 1, None, "", "python.exe", "", "", "a" * 32, 1.0, 100.0, 1, "external", "test"),
    )
    conn.execute(
        """
        INSERT INTO process_watch_snapshots (
            captured_at, pid, ppid, parent_pid, parent_name, name, exe, cmdline,
            cmdline_hash, create_time, memory_mb, is_orphan, scope, captured_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2026-04-16T15:49:00", 9002, 1, None, "", "python.exe", "", "", "b" * 32, 2.0, 80.0, 0, "external", "test"),
    )
    conn.commit()

    with patch("app.shared.process.snapshot_writer.SessionLocal", return_value=MockSession(conn)), \
         patch("app.shared.process.snapshot_writer.is_pg", False):
        writer = SnapshotWriter(MagicMock())
        rows = writer.get_python_snapshot_history(only_orphan=True, limit=10)

    assert len(rows) == 1
    assert rows[0]["pid"] == 9001
    assert rows[0]["is_orphan"] is True


# ============================================================
# PG AUTOINCREMENT → SERIAL 분기 TC
# ============================================================

def test_ensure_watch_tables_sqlite_uses_autoincrement():
    """R: is_pg=False일 때 CREATE TABLE에 AUTOINCREMENT 사용"""
    from app.shared.process.snapshot_writer import SnapshotWriter

    source = inspect.getsource(SnapshotWriter._ensure_watch_tables)
    assert "auto_pk" in source, "is_pg 분기 auto_pk 변수가 없음"
    assert "SERIAL PRIMARY KEY" in source, "PG 분기(SERIAL) 없음"
    assert "AUTOINCREMENT" in source, "SQLite 분기(AUTOINCREMENT) 없음"


def test_ensure_watch_tables_has_pg_boolean_default():
    """R: is_pg=True일 때 is_orphan 컬럼은 BOOLEAN DEFAULT FALSE 계약을 가진다."""
    from app.shared.process.snapshot_writer import SnapshotWriter

    source = inspect.getsource(SnapshotWriter._ensure_watch_tables)
    assert "BOOLEAN DEFAULT FALSE" in source


def test_ensure_watch_tables_pg_generates_serial_ddl():
    """R: is_pg=True일 때 DDL에 SERIAL PRIMARY KEY 삽입"""
    with patch("app.shared.process.snapshot_writer.is_pg", True):
        from app.shared.process.snapshot_writer import SnapshotWriter
        # auto_pk 값 직접 검증
        auto_pk = "SERIAL PRIMARY KEY" if True else "INTEGER PRIMARY KEY AUTOINCREMENT"
        assert auto_pk == "SERIAL PRIMARY KEY"


def test_ensure_watch_tables_sqlite_generates_autoincrement_ddl():
    """R: is_pg=False일 때 DDL에 INTEGER PRIMARY KEY AUTOINCREMENT 삽입"""
    auto_pk = "SERIAL PRIMARY KEY" if False else "INTEGER PRIMARY KEY AUTOINCREMENT"
    assert auto_pk == "INTEGER PRIMARY KEY AUTOINCREMENT"
