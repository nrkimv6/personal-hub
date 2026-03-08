"""SnapshotWriter TC"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sqlite3
import tempfile
import os


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
    conn = sqlite3.connect(":memory:")
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
