"""프로세스 스냅샷 기록 모듈."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import psutil
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal, is_pg

if TYPE_CHECKING:
    from app.shared.process.registry import ProcessRegistry

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WATCH_EVENTS_LOG = _PROJECT_ROOT / "logs" / "process_watch_events.jsonl"
_KILL_AUDIT_LOG = _PROJECT_ROOT / "logs" / "process_watch_kill_audit.jsonl"


class SnapshotWriter:
    """프로세스 스냅샷과 조치 로그를 DB/JSONL에 기록한다."""

    def __init__(self, registry: "ProcessRegistry") -> None:
        self.registry = registry
        self._retention_days = max(1, int(getattr(settings, "PROCESS_WATCH_RETENTION_DAYS", 7)))
        rotate_mb = float(getattr(settings, "PROCESS_WATCH_LOG_ROTATE_MB", 20))
        self._rotate_bytes = int(max(1.0, rotate_mb) * 1024 * 1024)

    @staticmethod
    def _cmdline_hash(cmdline: str) -> str:
        value = (cmdline or "").strip()
        if not value:
            return ""
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:32]

    @staticmethod
    def _join_cmdline(cmdline_parts: Any) -> str:
        if not cmdline_parts:
            return ""
        if isinstance(cmdline_parts, (list, tuple)):
            return " ".join(str(x) for x in cmdline_parts if x is not None).strip()
        return str(cmdline_parts).strip()

    @staticmethod
    def _safe_bool(value: Any) -> bool:
        return bool(value)

    @staticmethod
    def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized.append(
                {
                    "captured_at": row.get("captured_at"),
                    "pid": row.get("pid"),
                    "ppid": row.get("ppid"),
                    "parent_pid": row.get("parent_pid"),
                    "parent_name": row.get("parent_name", ""),
                    "name": row.get("name", ""),
                    "exe": row.get("exe", ""),
                    "cmdline": row.get("cmdline", ""),
                    "cmdline_hash": row.get("cmdline_hash", ""),
                    "create_time": row.get("create_time"),
                    "memory_mb": row.get("memory_mb"),
                    "is_orphan": bool(row.get("is_orphan")),
                    "scope": row.get("scope", "external"),
                    "captured_by": row.get("captured_by", "periodic"),
                }
            )
        return normalized

    @staticmethod
    def _infer_scope(name: str, exe: str, cmdline: str) -> str:
        joined = " ".join((name or "", exe or "", cmdline or "")).lower().replace("\\", "/")
        project_hint = str(_PROJECT_ROOT).lower().replace("\\", "/")
        # browser_workers.py는 CLI facade로 유지되며, 프로세스 식별 앵커도 그대로 사용한다.
        monitor_keywords = (
            "monitor-page",
            "browser_workers.py",
            "service_run.py",
            "app/main.py",
            "/tools/monitor-page/",
        )
        if project_hint in joined:
            return "monitor_page"
        for keyword in monitor_keywords:
            if keyword in joined:
                return "monitor_page"
        return "external"

    @staticmethod
    def _resolve_parent(ppid: Optional[int]) -> tuple[Optional[int], str]:
        if ppid is None or ppid <= 0:
            return None, ""
        try:
            parent_proc = psutil.Process(ppid)
            parent_name = parent_proc.name() or ""
            grand_parent = parent_proc.ppid()
            return (int(grand_parent) if grand_parent else None), parent_name
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None, ""

    def _ensure_watch_tables(self, db: Any) -> None:
        auto_pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_default = "BOOLEAN DEFAULT FALSE" if is_pg else "INTEGER DEFAULT 0"
        db.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS process_watch_snapshots (
                    id {auto_pk},
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
                    is_orphan {bool_default},
                    scope TEXT DEFAULT 'external',
                    captured_by TEXT DEFAULT 'periodic'
                )
                """
            )
        )
        db.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS process_watch_actions (
                    id {auto_pk},
                    acted_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    cmdline_hash TEXT,
                    reason TEXT,
                    actor TEXT,
                    result TEXT,
                    detail TEXT
                )
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pws_captured_at ON process_watch_snapshots(captured_at)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pws_pid ON process_watch_snapshots(pid)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pws_orphan ON process_watch_snapshots(is_orphan)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pws_memory ON process_watch_snapshots(memory_mb)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pws_hash ON process_watch_snapshots(cmdline_hash)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pwa_acted_at ON process_watch_actions(acted_at)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pwa_pid ON process_watch_actions(pid)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_pwa_hash ON process_watch_actions(cmdline_hash)"))

    def _purge_watch_rows(self, db: Any) -> None:
        window = f"-{self._retention_days} days"
        if is_pg:
            db.execute(
                text("DELETE FROM process_watch_snapshots WHERE captured_at < NOW() + :window::interval"),
                {"window": window},
            )
            db.execute(
                text("DELETE FROM process_watch_actions WHERE acted_at < NOW() + :window::interval"),
                {"window": window},
            )
        else:
            db.execute(
                text("DELETE FROM process_watch_snapshots WHERE captured_at < datetime('now', :window)"),
                {"window": window},
            )
            db.execute(
                text("DELETE FROM process_watch_actions WHERE acted_at < datetime('now', :window)"),
                {"window": window},
            )

    def _rotate_jsonl_if_needed(self, path: Path) -> None:
        if not path.exists():
            return
        if path.stat().st_size < self._rotate_bytes:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated = path.with_name(f"{path.stem}.{timestamp}.jsonl")
        path.rename(rotated)

    def _purge_old_jsonl_files(self, path: Path) -> None:
        base_name = path.stem
        now = datetime.now()
        cutoff = now - timedelta(days=self._retention_days)
        for candidate in path.parent.glob(f"{base_name}*.jsonl"):
            try:
                modified = datetime.fromtimestamp(candidate.stat().st_mtime)
                if modified < cutoff:
                    candidate.unlink(missing_ok=True)
            except OSError:
                continue

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_jsonl_if_needed(path)
            with path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._purge_old_jsonl_files(path)
        except Exception as exc:
            logger.warning("process-watch JSONL append 실패 (%s): %s", path, exc)

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
                        (:captured_at, :pid, :ppid, :name, :exe, :role, :memory_mb, :is_orphan, NULL)
                    """,
                    {
                        "captured_at": captured_at,
                        "pid": pid,
                        "ppid": ppid,
                        "name": entry.get("name", ""),
                        "exe": entry.get("exe", ""),
                        "role": entry.get("role", ""),
                        "memory_mb": memory_mb,
                        "is_orphan": self._safe_bool(False),
                    },
                )
            db.commit()

    def _capture_python_processes_sync(
        self,
        min_memory_mb: float = 0.0,
        limit: int = 200,
        captured_by: str = "periodic",
    ) -> int:
        captured_at = datetime.now().isoformat()
        rows: list[dict[str, Any]] = []

        for proc in psutil.process_iter(
            ["pid", "name", "exe", "ppid", "cmdline", "memory_info", "create_time"]
        ):
            try:
                info = proc.info
                name = info.get("name") or ""
                exe = info.get("exe") or ""
                exe_name = Path(exe).name.lower() if exe else ""
                if "python" not in name.lower() and "python" not in exe_name:
                    continue

                memory_info = info.get("memory_info")
                memory_mb = round(
                    (memory_info.rss if memory_info is not None else 0.0) / (1024 * 1024),
                    2,
                )
                if memory_mb < min_memory_mb:
                    continue

                cmdline = self._join_cmdline(info.get("cmdline"))
                cmdline_hash = self._cmdline_hash(cmdline)

                ppid_raw = info.get("ppid")
                ppid: Optional[int]
                try:
                    ppid = int(ppid_raw) if ppid_raw is not None else None
                except (TypeError, ValueError):
                    ppid = None
                parent_pid, parent_name = self._resolve_parent(ppid)
                is_orphan = bool(ppid and ppid > 0 and not psutil.pid_exists(ppid))

                create_time_val = info.get("create_time")
                create_time = float(create_time_val) if create_time_val is not None else None

                rows.append(
                    {
                        "captured_at": captured_at,
                        "pid": int(info["pid"]),
                        "ppid": ppid,
                        "parent_pid": parent_pid,
                        "parent_name": parent_name,
                        "name": name,
                        "exe": exe,
                        "cmdline": cmdline,
                        "cmdline_hash": cmdline_hash,
                        "create_time": create_time,
                        "memory_mb": memory_mb,
                        "is_orphan": self._safe_bool(is_orphan),
                        "scope": self._infer_scope(name, exe, cmdline),
                        "captured_by": captured_by,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        rows.sort(key=lambda item: float(item.get("memory_mb", 0.0)), reverse=True)
        if limit > 0:
            rows = rows[:limit]

        with SessionLocal() as db:
            self._ensure_watch_tables(db)
            for row in rows:
                db.execute(
                    text(
                        """
                        INSERT INTO process_watch_snapshots (
                            captured_at, pid, ppid, parent_pid, parent_name,
                            name, exe, cmdline, cmdline_hash, create_time, memory_mb,
                            is_orphan, scope, captured_by
                        )
                        VALUES (
                            :captured_at, :pid, :ppid, :parent_pid, :parent_name,
                            :name, :exe, :cmdline, :cmdline_hash, :create_time, :memory_mb,
                            :is_orphan, :scope, :captured_by
                        )
                        """
                    ),
                    row,
                )
            self._purge_watch_rows(db)
            db.commit()

        self._append_jsonl(
            _WATCH_EVENTS_LOG,
            {
                "timestamp": captured_at,
                "event": "snapshot",
                "captured_by": captured_by,
                "count": len(rows),
                "items": self._normalize_rows(rows),
            },
        )
        return len(rows)

    async def capture_python_processes(
        self,
        min_memory_mb: float = 0.0,
        limit: int = 200,
        captured_by: str = "periodic",
    ) -> int:
        return await asyncio.to_thread(
            self._capture_python_processes_sync,
            min_memory_mb,
            limit,
            captured_by,
        )

    def get_latest_python_snapshots(
        self,
        min_memory_mb: float = 0.0,
        scope: Optional[str] = None,
        limit: int = 200,
    ) -> tuple[Optional[str], list[dict[str, Any]]]:
        where_parts = ["captured_at = :captured_at", "memory_mb >= :min_memory_mb"]
        params: dict[str, Any] = {
            "min_memory_mb": float(min_memory_mb),
            "limit": int(max(1, min(limit, 500))),
        }
        if scope:
            where_parts.append("scope = :scope")
            params["scope"] = scope

        query = text(
            f"""
            SELECT
                captured_at, pid, ppid, parent_pid, parent_name, name, exe, cmdline,
                cmdline_hash, create_time, memory_mb, is_orphan, scope, captured_by
            FROM process_watch_snapshots
            WHERE {' AND '.join(where_parts)}
            ORDER BY memory_mb DESC
            LIMIT :limit
            """
        )

        try:
            with SessionLocal() as db:
                self._ensure_watch_tables(db)
                latest_row = db.execute(
                    text("SELECT MAX(captured_at) AS captured_at FROM process_watch_snapshots")
                ).fetchone()
                latest_captured_at = latest_row[0] if latest_row else None
                if not latest_captured_at:
                    return None, []
                params["captured_at"] = latest_captured_at
                rows = db.execute(query, params).fetchall()
        except Exception as exc:
            logger.warning("get_latest_python_snapshots 실패: %s", exc)
            return None, []

        result = [dict(row._mapping) for row in rows]
        return latest_captured_at, self._normalize_rows(result)

    def get_python_snapshot_history(
        self,
        min_memory_mb: float = 0.0,
        only_orphan: bool = False,
        scope: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        where_parts = ["memory_mb >= :min_memory_mb"]
        params: dict[str, Any] = {
            "min_memory_mb": float(min_memory_mb),
            "limit": int(max(1, min(limit, 1000))),
        }
        if only_orphan:
            where_parts.append("is_orphan = :only_orphan")
            params["only_orphan"] = self._safe_bool(True)
        if scope:
            where_parts.append("scope = :scope")
            params["scope"] = scope

        query = text(
            f"""
            SELECT
                captured_at, pid, ppid, parent_pid, parent_name, name, exe, cmdline,
                cmdline_hash, create_time, memory_mb, is_orphan, scope, captured_by
            FROM process_watch_snapshots
            WHERE {' AND '.join(where_parts)}
            ORDER BY captured_at DESC, memory_mb DESC
            LIMIT :limit
            """
        )

        try:
            with SessionLocal() as db:
                self._ensure_watch_tables(db)
                rows = db.execute(query, params).fetchall()
        except Exception as exc:
            logger.warning("get_python_snapshot_history 실패: %s", exc)
            return []
        return self._normalize_rows([dict(row._mapping) for row in rows])

    def record_kill_action(
        self,
        action: str,
        pid: int,
        cmdline_hash: str,
        reason: str,
        actor: str,
        result: str,
        detail: str = "",
    ) -> None:
        acted_at = datetime.now().isoformat()
        payload = {
            "acted_at": acted_at,
            "action": action,
            "pid": pid,
            "cmdline_hash": cmdline_hash or "",
            "reason": reason or "",
            "actor": actor or "unknown",
            "result": result,
            "detail": detail or "",
        }
        try:
            with SessionLocal() as db:
                self._ensure_watch_tables(db)
                db.execute(
                    text(
                        """
                        INSERT INTO process_watch_actions (
                            acted_at, action, pid, cmdline_hash, reason, actor, result, detail
                        )
                        VALUES (
                            :acted_at, :action, :pid, :cmdline_hash, :reason, :actor, :result, :detail
                        )
                        """
                    ),
                    payload,
                )
                self._purge_watch_rows(db)
                db.commit()
        except Exception as exc:
            logger.warning("record_kill_action 실패 (pid=%s): %s", pid, exc)

        self._append_jsonl(
            _KILL_AUDIT_LOG,
            {
                "timestamp": acted_at,
                "event": "kill",
                **payload,
            },
        )

    def record_orphan_action(self, pid: int, name: str, action: str) -> None:
        """고아 프로세스에 대해 취해진 조치를 기록한다."""
        captured_at = datetime.now().isoformat()
        try:
            with SessionLocal() as db:
                db.execute(
                    """
                    INSERT INTO process_snapshots
                        (captured_at, pid, name, is_orphan, action_taken)
                    VALUES
                        (:captured_at, :pid, :name, :is_orphan, :action_taken)
                    """,
                    {
                        "captured_at": captured_at,
                        "pid": pid,
                        "name": name,
                        "is_orphan": self._safe_bool(True),
                        "action_taken": action,
                    },
                )
                db.commit()
        except Exception as exc:
            logger.warning("record_orphan_action 실패 (pid=%s): %s", pid, exc)

    def purge_old(self, days: int = 7) -> None:
        """오래된 스냅샷을 삭제한다."""
        try:
            with SessionLocal() as db:
                if is_pg:
                    db.execute(
                        text(f"DELETE FROM process_snapshots WHERE captured_at < NOW() - INTERVAL '{days} days'")
                    )
                else:
                    db.execute(
                        text(f"DELETE FROM process_snapshots WHERE captured_at < datetime('now', '-{days} days')")
                    )
                self._purge_watch_rows(db)
                db.commit()
        except Exception as exc:
            logger.warning("purge_old 실패: %s", exc)
