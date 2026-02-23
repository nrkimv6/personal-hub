"""메타데이터 추출 오케스트레이터"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Callable
from .task_progress import TaskProgressManager
from .metadata import music, archive, installer, document, video, image


class MetadataExtractor:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def extract(self, task_id: Optional[int] = None,
                progress_callback: Optional[Callable] = None) -> dict:
        stats = {"total": 0, "processed": 0, "errors": 0}
        progress_mgr = TaskProgressManager(self.db) if task_id else None

        # pending 파일 조회
        rows = self.db.execute(text(
            "SELECT id, file_path, file_group FROM fc_files WHERE status = 'pending'"
        )).fetchall()

        stats["total"] = len(rows)
        for i, row in enumerate(rows):
            if self._stop_flag:
                break
            try:
                file_id, file_path, file_group = row
                self._extract_one(file_id, file_path, file_group)
                self.db.execute(text(
                    "UPDATE fc_files SET status = 'metadata_extracted' WHERE id = :id"
                ), {"id": file_id})
                self.db.commit()
                stats["processed"] += 1
            except Exception as e:
                stats["errors"] += 1

            if (i + 1) % 50 == 0 and progress_mgr and task_id:
                progress_mgr.update_progress(task_id, i + 1, str(row[1]))

        return stats

    def _extract_one(self, file_id: int, file_path: str, file_group: str):
        from pathlib import Path
        if not Path(file_path).exists():
            return
        if file_group == "music":
            music.extract(file_id, file_path, self.db)
        elif file_group == "archive":
            archive.extract(file_id, file_path, self.db)
        elif file_group == "installer":
            installer.extract(file_id, file_path, self.db)
        elif file_group == "document":
            document.extract(file_id, file_path, self.db)
        elif file_group == "video":
            video.extract(file_id, file_path, self.db)
        elif file_group == "image":
            image.extract(file_id, file_path, self.db)
