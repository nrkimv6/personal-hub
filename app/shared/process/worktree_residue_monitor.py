"""test worktree residue monitoring state/jsonl store."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorktreeResidueMonitor:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    EVENTS_PATH = PROJECT_ROOT / "logs" / "worktree_residue_events.jsonl"
    STATUS_PATH = PROJECT_ROOT / "logs" / "worktree_residue_status.json"
    _lock = threading.Lock()

    @classmethod
    def _utcnow(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _read_status(cls) -> dict[str, Any]:
        if not cls.STATUS_PATH.exists():
            return {
                "version": 1,
                "created_at": cls._utcnow(),
                "updated_at": None,
                "baseline_zero_confirmed_at": None,
                "latest_scan_at": None,
                "latest_source": None,
                "latest_test_branch_count": 0,
                "latest_test_branches": [],
                "max_test_branch_count_since_baseline": 0,
                "nonzero_seen_since_baseline": False,
                "last_nonzero_at": None,
                "last_nonzero_branches": [],
                "force_cleanup_event_count": 0,
                "force_cleanup_branch_count": 0,
                "orphan_cleanup_event_count": 0,
                "orphan_cleanup_branch_count": 0,
                "last_force_cleanup": None,
                "last_orphan_cleanup": None,
            }

        try:
            return json.loads(cls.STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {
                "version": 1,
                "created_at": cls._utcnow(),
            }

    @classmethod
    def _write_status(cls, status: dict[str, Any]) -> None:
        cls.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = cls.STATUS_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(cls.STATUS_PATH)

    @classmethod
    def _append_event(cls, payload: dict[str, Any]) -> None:
        cls.EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with cls.EVENTS_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @classmethod
    def record_scan(cls, branches: list[str], *, source: str) -> dict[str, Any]:
        normalized = sorted({branch for branch in branches if branch})
        now = cls._utcnow()

        with cls._lock:
            status = cls._read_status()
            previous_count = int(status.get("latest_test_branch_count") or 0)
            previous_branches = list(status.get("latest_test_branches") or [])
            changed = previous_count != len(normalized) or previous_branches != normalized

            status["updated_at"] = now
            status["latest_scan_at"] = now
            status["latest_source"] = source
            status["latest_test_branch_count"] = len(normalized)
            status["latest_test_branches"] = normalized

            if normalized:
                if status.get("baseline_zero_confirmed_at"):
                    status["nonzero_seen_since_baseline"] = True
                    status["max_test_branch_count_since_baseline"] = max(
                        int(status.get("max_test_branch_count_since_baseline") or 0),
                        len(normalized),
                    )
                status["last_nonzero_at"] = now
                status["last_nonzero_branches"] = normalized
            elif not status.get("baseline_zero_confirmed_at"):
                status["baseline_zero_confirmed_at"] = now

            cls._write_status(status)

            if changed or not normalized:
                cls._append_event(
                    {
                        "type": "scan",
                        "recorded_at": now,
                        "source": source,
                        "test_branch_count": len(normalized),
                        "test_branches": normalized,
                    }
                )

            return status

    @classmethod
    def record_cleanup(
        cls,
        *,
        event_type: str,
        branches: list[str],
        source: str,
        runner_id: str | None = None,
        test_source: str | None = None,
        worktree_path: str | None = None,
    ) -> dict[str, Any]:
        now = cls._utcnow()
        normalized = sorted({branch for branch in branches if branch})

        with cls._lock:
            status = cls._read_status()
            status["updated_at"] = now

            payload = {
                "type": event_type,
                "recorded_at": now,
                "source": source,
                "branches": normalized,
                "runner_id": runner_id,
                "test_source": test_source,
                "worktree_path": worktree_path,
            }

            if event_type == "force_cleanup":
                status["force_cleanup_event_count"] = int(
                    status.get("force_cleanup_event_count") or 0
                ) + 1
                status["force_cleanup_branch_count"] = int(
                    status.get("force_cleanup_branch_count") or 0
                ) + len(normalized)
                status["last_force_cleanup"] = payload
            elif event_type == "orphan_cleanup":
                status["orphan_cleanup_event_count"] = int(
                    status.get("orphan_cleanup_event_count") or 0
                ) + 1
                status["orphan_cleanup_branch_count"] = int(
                    status.get("orphan_cleanup_branch_count") or 0
                ) + len(normalized)
                status["last_orphan_cleanup"] = payload

            cls._write_status(status)
            cls._append_event(payload)
            return status
