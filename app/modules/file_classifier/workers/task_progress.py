"""
작업 진행 추적 매니저

모든 장기 작업(스캔, 메타데이터 추출, 분류, 이동)의 진행 상태를 DB에 저장/조회.
서버 재시작 후에도 진행 상태 유지.
"""

from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session


class TaskProgressManager:
    """작업 진행 상태 DB CRUD 래퍼 (fc_task_progress 테이블)"""

    def __init__(self, db: Session):
        self.db = db

    def start_task(self, task_type: str, total_items: int) -> int:
        """새 작업 시작 — INSERT + status='running'"""
        # 기존 running 작업이 있으면 failed로 변경
        self.db.execute(
            text("""
                UPDATE fc_task_progress
                SET status = 'failed', error_message = 'superseded by new task'
                WHERE task_type = :task_type AND status = 'running'
            """),
            {"task_type": task_type}
        )

        self.db.execute(
            text("""
                INSERT INTO fc_task_progress (task_type, status, total_items, processed_items, started_at)
                VALUES (:task_type, 'running', :total_items, 0, :now)
            """),
            {
                "task_type": task_type,
                "total_items": total_items,
                "now": datetime.now().isoformat(),
            }
        )
        self.db.commit()

        result = self.db.execute(
            text("SELECT id FROM fc_task_progress WHERE task_type = :task_type ORDER BY id DESC LIMIT 1"),
            {"task_type": task_type}
        ).fetchone()
        return result.id

    def update_progress(self, task_id: int, processed: int, current_item: str = None):
        """진행 상태 업데이트"""
        self.db.execute(
            text("""
                UPDATE fc_task_progress
                SET processed_items = :processed, current_item = :current_item
                WHERE id = :task_id
            """),
            {
                "task_id": task_id,
                "processed": processed,
                "current_item": current_item,
            }
        )
        self.db.commit()

    def complete_task(self, task_id: int):
        """작업 완료"""
        self.db.execute(
            text("""
                UPDATE fc_task_progress
                SET status = 'completed', completed_at = :now
                WHERE id = :task_id
            """),
            {"task_id": task_id, "now": datetime.now().isoformat()}
        )
        self.db.commit()

    def fail_task(self, task_id: int, error: str):
        """작업 실패"""
        self.db.execute(
            text("""
                UPDATE fc_task_progress
                SET status = 'failed', error_message = :error
                WHERE id = :task_id
            """),
            {"task_id": task_id, "error": error}
        )
        self.db.commit()

    def pause_task(self, task_id: int):
        """작업 일시 중지"""
        self.db.execute(
            text("""
                UPDATE fc_task_progress
                SET status = 'paused'
                WHERE id = :task_id
            """),
            {"task_id": task_id}
        )
        self.db.commit()

    def get_task(self, task_id: int) -> dict | None:
        """작업 조회"""
        row = self.db.execute(
            text("SELECT * FROM fc_task_progress WHERE id = :task_id"),
            {"task_id": task_id}
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_latest(self, task_type: str) -> dict | None:
        """최신 작업 1건 조회"""
        row = self.db.execute(
            text("SELECT * FROM fc_task_progress WHERE task_type = :task_type ORDER BY id DESC LIMIT 1"),
            {"task_type": task_type}
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_running(self, task_type: str) -> dict | None:
        """실행 중인 작업 조회"""
        row = self.db.execute(
            text("""
                SELECT * FROM fc_task_progress
                WHERE task_type = :task_type AND status = 'running'
                ORDER BY id DESC LIMIT 1
            """),
            {"task_type": task_type}
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_history(self, task_type: str, limit: int = 10) -> list[dict]:
        """작업 이력 조회"""
        rows = self.db.execute(
            text("SELECT * FROM fc_task_progress WHERE task_type = :task_type ORDER BY id DESC LIMIT :limit"),
            {"task_type": task_type, "limit": limit}
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row) -> dict:
        """DB row → dict 변환"""
        return {
            "id": row.id,
            "task_type": row.task_type,
            "status": row.status,
            "total_items": row.total_items,
            "processed_items": row.processed_items,
            "current_item": row.current_item,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "error_message": row.error_message,
        }
