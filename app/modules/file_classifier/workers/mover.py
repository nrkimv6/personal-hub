"""파일 이동기 (dry-run / execute / undo)"""
import shutil
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional


class MoveManager:
    def __init__(self, db: Session):
        self.db = db

    def preview(self, file_ids: Optional[list] = None) -> list:
        """dry-run: suggested_path 계산"""
        from ..config import settings
        target_root = settings.TARGET_ROOT_FOLDER
        if not target_root:
            return []

        query = """
            SELECT f.id, f.file_path, f.file_name, c.full_path as category_path
            FROM fc_files f
            JOIN fc_categories c ON c.id = COALESCE(f.final_category_id, f.rule_category_id, f.llm_category_id)
            WHERE f.status = 'approved'
        """
        params = {}
        if file_ids:
            placeholders = ",".join([f":id{i}" for i in range(len(file_ids))])
            query += f" AND f.id IN ({placeholders})"
            params = {f"id{i}": fid for i, fid in enumerate(file_ids)}

        rows = self.db.execute(text(query), params).fetchall()
        results = []
        for row in rows:
            fid, src, fname, cat_path = row
            dest = self._compute_dest(target_root, cat_path, fname)
            self.db.execute(text(
                "UPDATE fc_files SET suggested_path = :path WHERE id = :id"
            ), {"path": str(dest), "id": fid})
            results.append({"file_id": fid, "source": src, "destination": str(dest), "category": cat_path})
        self.db.commit()
        return results

    def execute(self, file_ids: Optional[list] = None) -> dict:
        """실제 이동"""
        stats = {"moved": 0, "errors": 0}
        query = """
            SELECT f.id, f.file_path, f.suggested_path
            FROM fc_files f
            WHERE f.suggested_path IS NOT NULL AND f.status = 'approved'
        """
        params = {}
        if file_ids:
            placeholders = ",".join([f":id{i}" for i in range(len(file_ids))])
            query += f" AND f.id IN ({placeholders})"
            params = {f"id{i}": fid for i, fid in enumerate(file_ids)}

        rows = self.db.execute(text(query), params).fetchall()
        for row in rows:
            fid, src, dest = row
            try:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(src, dest)
                self.db.execute(text(
                    "UPDATE fc_files SET moved_path = :dest, status = 'moved', moved_at = CURRENT_TIMESTAMP WHERE id = :id"
                ), {"dest": dest, "id": fid})
                self.db.commit()
                stats["moved"] += 1
            except Exception as e:
                stats["errors"] += 1
        return stats

    def undo(self, file_id: int) -> bool:
        row = self.db.execute(text(
            "SELECT file_path, moved_path FROM fc_files WHERE id = :id AND status = 'moved'"
        ), {"id": file_id}).fetchone()
        if not row:
            return False
        original, moved = row
        try:
            Path(original).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(moved, original)
            self.db.execute(text(
                "UPDATE fc_files SET moved_path = NULL, status = 'approved', moved_at = NULL WHERE id = :id"
            ), {"id": file_id})
            self.db.commit()
            return True
        except Exception:
            return False

    def _compute_dest(self, root: str, cat_path: str, filename: str) -> Path:
        dest = Path(root) / cat_path / filename
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = dest.parent / f"{stem}_{counter:03d}{suffix}"
                counter += 1
        return dest
