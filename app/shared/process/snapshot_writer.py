"""프로세스 스냅샷 기록 모듈.

process_snapshots 테이블에 프로세스 상태를 기록하고 오래된 레코드를 정리한다.
"""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import psutil

from app.core.database import SessionLocal

if TYPE_CHECKING:
    from app.shared.process.registry import ProcessRegistry

logger = logging.getLogger(__name__)


class SnapshotWriter:
    """process_snapshots 테이블에 프로세스 스냅샷을 기록한다."""

    def __init__(self, registry: "ProcessRegistry") -> None:
        self.registry = registry

    async def capture(self) -> None:
        """등록된 모든 프로세스의 현재 상태를 DB에 저장한다."""
        all_procs = await self.registry.get_all()
        captured_at = datetime.now().isoformat()

        with SessionLocal() as db:
            for pid, entry in all_procs.items():
                memory_mb: float = 0.0
                try:
                    proc = psutil.Process(pid)
                    memory_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

                try:
                    ppid_val = entry.get("ppid")
                    ppid = int(ppid_val) if ppid_val is not None else None
                except (ValueError, TypeError):
                    ppid = None

                db.execute(
                    """
                    INSERT INTO process_snapshots
                        (captured_at, pid, ppid, name, exe, role, memory_mb, is_orphan, action_taken)
                    VALUES
                        (:captured_at, :pid, :ppid, :name, :exe, :role, :memory_mb, 0, NULL)
                    """,
                    {
                        "captured_at": captured_at,
                        "pid": pid,
                        "ppid": ppid,
                        "name": entry.get("name", ""),
                        "exe": entry.get("exe", ""),
                        "role": entry.get("role", ""),
                        "memory_mb": memory_mb,
                    },
                )
            db.commit()

    def record_orphan_action(self, pid: int, name: str, action: str) -> None:
        """고아 프로세스에 대해 취해진 조치를 기록한다.

        Args:
            pid: 프로세스 ID
            name: 프로세스 이름
            action: 취해진 조치 (예: "terminated")
        """
        captured_at = datetime.now().isoformat()
        try:
            with SessionLocal() as db:
                db.execute(
                    """
                    INSERT INTO process_snapshots
                        (captured_at, pid, name, is_orphan, action_taken)
                    VALUES
                        (:captured_at, :pid, :name, 1, :action_taken)
                    """,
                    {
                        "captured_at": captured_at,
                        "pid": pid,
                        "name": name,
                        "action_taken": action,
                    },
                )
                db.commit()
        except Exception as exc:
            logger.warning("record_orphan_action 실패 (pid=%s): %s", pid, exc)

    def purge_old(self, days: int = 7) -> None:
        """오래된 스냅샷을 삭제한다.

        Args:
            days: 보관 기간 (일). 이보다 오래된 레코드는 삭제.
        """
        try:
            with SessionLocal() as db:
                db.execute(
                    f"DELETE FROM process_snapshots WHERE captured_at < datetime('now', '-{days} days')"
                )
                db.commit()
        except Exception as exc:
            logger.warning("purge_old 실패: %s", exc)
