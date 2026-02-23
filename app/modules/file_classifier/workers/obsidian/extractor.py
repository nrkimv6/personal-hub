"""옵시디언 메모에서 유용 정보 추출"""
import json
import re
from sqlalchemy.orm import Session
from sqlalchemy import text
from pathlib import Path
from typing import Optional, Callable

TODO_PATTERN = re.compile(r'-\s*\[[ x]\]\s*(.+)', re.MULTILINE)
URL_PATTERN = re.compile(r'https?://\S+')

class ObsidianExtractor:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def extract(self, progress_callback: Optional[Callable] = None) -> dict:
        stats = {"total": 0, "extracted": 0, "errors": 0}

        notes = self.db.execute(text(
            "SELECT id, file_path FROM obsidian_notes WHERE note_type = 'memo' AND status = 'classified'"
        )).fetchall()

        stats["total"] = len(notes)
        for i, row in enumerate(notes):
            if self._stop_flag:
                break
            try:
                note_id, file_path = row
                extracted = self._extract_one(file_path)
                self.db.execute(text(
                    "UPDATE obsidian_notes SET extracted_json = :data, status = 'extracted' WHERE id = :id"
                ), {"data": json.dumps(extracted, ensure_ascii=False), "id": note_id})
                self.db.commit()
                stats["extracted"] += 1
            except Exception:
                stats["errors"] += 1

            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(i + 1, stats["total"], str(row[1]))

        return stats

    def _extract_one(self, file_path: str) -> dict:
        try:
            content = Path(file_path).read_text(encoding='utf-8', errors='replace')
        except Exception:
            return {}

        todos = TODO_PATTERN.findall(content)
        urls = URL_PATTERN.findall(content)

        # 코드 스니펫 추출
        code_blocks = re.findall(r'```[\w]*\n(.*?)```', content, re.DOTALL)

        return {
            "todos": todos[:20],
            "urls": list(set(urls))[:20],
            "code_snippets": [c[:200] for c in code_blocks[:5]],
        }
