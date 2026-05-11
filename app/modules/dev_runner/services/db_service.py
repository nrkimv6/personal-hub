"""Legacy dev-runner ``tasks.db`` compatibility shim.

The SQLite ``tasks.db`` service was removed during the PostgreSQL cutover. This
module remains importable so stale imports do not break the API process, but all
data access must go through the current dev-runner services and PostgreSQL read
models.
"""

from __future__ import annotations


class LegacyTasksDbRemovedError(RuntimeError):
    """Raised when removed ``tasks.db`` APIs are called."""


class DBService:
    """Import-safe placeholder for the removed SQLite tasks service."""

    def __init__(self, *args, **kwargs) -> None:
        self.db_path = None

    @staticmethod
    def _removed() -> None:
        raise LegacyTasksDbRemovedError(
            "dev-runner tasks.db has been removed; use PostgreSQL-backed dev-runner services instead"
        )

    def get_tasks(self, *args, **kwargs):
        self._removed()

    def get_task_by_id(self, *args, **kwargs):
        self._removed()

    def delete_task(self, *args, **kwargs):
        self._removed()

    def delete_completed_tasks(self, *args, **kwargs):
        self._removed()

    def delete_old_tasks(self, *args, **kwargs):
        self._removed()

    def get_stats(self, *args, **kwargs):
        self._removed()

    def get_history(self, *args, **kwargs):
        self._removed()

    def find_duplicate_tasks(self, *args, **kwargs):
        self._removed()

    def get_stream_logs(self, *args, **kwargs):
        self._removed()

    def get_latest_cycle_id(self, *args, **kwargs):
        self._removed()


db_service = DBService()

__all__ = ["db_service", "DBService", "LegacyTasksDbRemovedError"]
