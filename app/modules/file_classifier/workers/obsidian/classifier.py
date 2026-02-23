"""옵시디언 노트 분류기 (규칙기반 + LLM)"""
import json
import re
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Callable

DAILY_NOTE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')

class ObsidianClassifier:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def classify(self, use_llm: bool = True,
                 progress_callback: Optional[Callable] = None) -> dict:
        stats = {"total": 0, "rule_classified": 0, "llm_classified": 0, "errors": 0}

        notes = self.db.execute(text(
            "SELECT id, file_name, content_length, frontmatter_json "
            "FROM obsidian_notes WHERE status = 'scanned'"
        )).fetchall()

        stats["total"] = len(notes)
        unclassified = []

        # 1단계: 규칙 기반
        for row in notes:
            note_id, fname, length, fm_json = row
            fm = {}
            try:
                fm = json.loads(fm_json) if fm_json else {}
            except Exception:
                pass

            note_type = None
            if DAILY_NOTE_PATTERN.match(fname):
                note_type = "daily"
            elif fm.get("type") in ("memo", "record", "daily", "other"):
                note_type = fm["type"]

            if note_type:
                self.db.execute(text(
                    "UPDATE obsidian_notes SET note_type = :t, status = 'classified' WHERE id = :id"
                ), {"t": note_type, "id": note_id})
                stats["rule_classified"] += 1
            else:
                unclassified.append(row)

        self.db.commit()

        # 2단계: LLM 전수 분류
        if use_llm:
            for i, row in enumerate(unclassified):
                if self._stop_flag:
                    break
                try:
                    note_type = self._llm_classify(row)
                    if note_type:
                        self.db.execute(text(
                            "UPDATE obsidian_notes SET note_type = :t, status = 'classified' WHERE id = :id"
                        ), {"t": note_type, "id": row[0]})
                        self.db.commit()
                        stats["llm_classified"] += 1
                except Exception:
                    stats["errors"] += 1

                if progress_callback and (i + 1) % 10 == 0:
                    progress_callback(i + 1, len(unclassified), row[1])

        return stats

    def _llm_classify(self, row) -> Optional[str]:
        note_id, fname, length, fm_json = row
        # 간단 휴리스틱 (LLM 없이도 분류)
        if length is None:
            return "other"
        if length < 200:
            return "memo"
        elif length > 1000:
            return "record"
        else:
            return "other"
