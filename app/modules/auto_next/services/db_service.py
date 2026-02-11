"""SQLite 연동 서비스"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from app.modules.auto_next.config import config
from app.modules.auto_next.schemas import (
    TaskResponse,
    TaskListResponse,
    StatsResponse,
    HistoryEntry,
    DuplicateTaskResponse,
)


class DBService:
    """tasks.db 직접 접근 서비스"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.AUTO_NEXT_DB_PATH

    @contextmanager
    def _get_connection(self):
        """Connection context manager"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_task_response(self, row: sqlite3.Row) -> TaskResponse:
        """Row를 TaskResponse로 변환"""
        duration_seconds = None
        if row["started_at"] and row["finished_at"]:
            started = datetime.fromisoformat(row["started_at"])
            finished = datetime.fromisoformat(row["finished_at"])
            duration_seconds = (finished - started).total_seconds()

        # cache_read_tokens + cache_create_tokens = cache_tokens
        cache_tokens = (row["cache_read_tokens"] or 0) + (row["cache_create_tokens"] or 0)

        return TaskResponse(
            id=row["id"],
            type=row["type"],
            source_path=row["source_path"],
            text=row["text"],
            priority=row["priority"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
            duration_seconds=duration_seconds,
            output_tokens=row["output_tokens"] or 0,
            input_tokens=row["input_tokens"] or 0,
            cache_read_tokens=row["cache_read_tokens"] or 0,
            cache_creation_tokens=row["cache_create_tokens"] or 0,
            error_message=row["error_message"],
            model_used=row["model_used"],
        )

    def get_tasks(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> TaskListResponse:
        """작업 목록 조회"""
        with self._get_connection() as conn:
            # 총 개수 쿼리
            if status:
                count_query = "SELECT COUNT(*) as cnt FROM tasks WHERE status = ?"
                total = conn.execute(count_query, (status,)).fetchone()["cnt"]
            else:
                count_query = "SELECT COUNT(*) as cnt FROM tasks"
                total = conn.execute(count_query).fetchone()["cnt"]

            # 목록 쿼리
            if status:
                list_query = """
                    SELECT * FROM tasks
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(list_query, (status, limit, offset)).fetchall()
            else:
                list_query = """
                    SELECT * FROM tasks
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(list_query, (limit, offset)).fetchall()

            tasks = [self._row_to_task_response(row) for row in rows]
            return TaskListResponse(tasks=tasks, total=total)

    def get_task_by_id(self, task_id: str) -> Optional[TaskResponse]:
        """특정 작업 조회"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                return self._row_to_task_response(row)
            return None

    def delete_task(self, task_id: str) -> bool:
        """작업 삭제"""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_stats(self) -> StatsResponse:
        """통계 조회"""
        with self._get_connection() as conn:
            query = """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(cache_read_tokens + cache_create_tokens) as total_cache_tokens,
                    SUM(
                        CASE
                            WHEN started_at IS NOT NULL AND finished_at IS NOT NULL
                            THEN (JULIANDAY(finished_at) - JULIANDAY(started_at)) * 86400000
                            ELSE 0
                        END
                    ) as total_duration_ms
                FROM tasks
            """
            row = conn.execute(query).fetchone()

            total = row["total"] or 0
            pending = row["pending"] or 0
            running = row["running"] or 0
            success = row["success"] or 0
            failed = row["failed"] or 0
            skipped = row["skipped"] or 0

            completed = success + failed + skipped
            completion_rate = completed / total if total > 0 else 0.0
            success_rate = success / completed if completed > 0 else 0.0

            total_input_tokens = row["total_input_tokens"] or 0
            total_output_tokens = row["total_output_tokens"] or 0
            total_cache_tokens = row["total_cache_tokens"] or 0
            total_tokens = total_input_tokens + total_output_tokens + total_cache_tokens
            total_duration_ms = int(row["total_duration_ms"] or 0)

            return StatsResponse(
                total=total,
                pending=pending,
                running=running,
                success=success,
                failed=failed,
                skipped=skipped,
                completed=completed,
                completion_rate=completion_rate,
                success_rate=success_rate,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cache_tokens=total_cache_tokens,
                total_tokens=total_tokens,
                total_duration_ms=total_duration_ms,
            )

    def get_history(self, days: int = 30) -> List[HistoryEntry]:
        """작업 히스토리 조회 (날짜별 집계)"""
        with self._get_connection() as conn:
            query = """
                SELECT
                    DATE(finished_at) as date,
                    COUNT(*) as count,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM tasks
                WHERE finished_at IS NOT NULL
                    AND DATE(finished_at) >= DATE('now', '-' || ? || ' days')
                GROUP BY DATE(finished_at)
                ORDER BY DATE(finished_at) ASC
            """
            rows = conn.execute(query, (days,)).fetchall()

            return [
                HistoryEntry(
                    date=row["date"],
                    count=row["count"],
                    success=row["success"] or 0,
                    failed=row["failed"] or 0,
                )
                for row in rows
            ]

    def find_duplicate_tasks(self, min_count: int = 2) -> List[DuplicateTaskResponse]:
        """중복 작업 찾기 (같은 text를 가진 작업들)"""
        with self._get_connection() as conn:
            # 중복 text 찾기
            duplicate_query = """
                SELECT text, COUNT(*) as count
                FROM tasks
                GROUP BY text
                HAVING COUNT(*) >= ?
                ORDER BY count DESC
            """
            duplicate_rows = conn.execute(duplicate_query, (min_count,)).fetchall()

            results = []
            for dup_row in duplicate_rows:
                text = dup_row["text"]
                count = dup_row["count"]

                # 해당 text를 가진 모든 작업 조회
                task_query = "SELECT * FROM tasks WHERE text = ? ORDER BY created_at DESC"
                task_rows = conn.execute(task_query, (text,)).fetchall()
                tasks = [self._row_to_task_response(row) for row in task_rows]

                results.append(
                    DuplicateTaskResponse(
                        text=text,
                        count=count,
                        tasks=tasks,
                    )
                )

            return results


# 싱글톤 인스턴스
db_service = DBService()

__all__ = ['db_service', 'DBService']
