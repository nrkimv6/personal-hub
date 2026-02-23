"""규칙 기반 분류 엔진"""
import re
import json
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Callable
from .task_progress import TaskProgressManager


class RuleClassifier:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def classify(self, task_id: Optional[int] = None,
                 progress_callback: Optional[Callable] = None) -> dict:
        stats = {"total": 0, "classified": 0, "unclassified": 0}

        # 규칙 로드 (priority DESC)
        rules = self.db.execute(text(
            "SELECT id, rule_type, category_id, rule_content, priority FROM fc_rules "
            "WHERE is_active = 1 ORDER BY priority DESC"
        )).fetchall()

        # metadata_extracted 또는 pending 파일 대상
        files = self.db.execute(text(
            "SELECT f.id, f.file_path, f.file_name, f.extension, f.file_group, "
            "f.metadata_json, m.artist_lang "
            "FROM fc_files f "
            "LEFT JOIN fc_music_meta m ON f.id = m.file_id "
            "WHERE f.status IN ('metadata_extracted', 'pending')"
        )).fetchall()

        stats["total"] = len(files)
        for i, file_row in enumerate(files):
            if self._stop_flag:
                break
            file_id = file_row[0]
            matched_category_id = self._match_rules(file_row, rules)

            if matched_category_id:
                self.db.execute(text(
                    "UPDATE fc_files SET rule_category_id = :cat_id, status = 'rule_classified', "
                    "classified_at = CURRENT_TIMESTAMP WHERE id = :id"
                ), {"cat_id": matched_category_id, "id": file_id})
                stats["classified"] += 1
            else:
                stats["unclassified"] += 1

            if (i + 1) % 100 == 0:
                self.db.commit()

        self.db.commit()
        return stats

    def _match_rules(self, file_row, rules) -> Optional[int]:
        file_id, file_path, file_name, extension, file_group, metadata_json, artist_lang = file_row
        meta = json.loads(metadata_json) if metadata_json else {}

        for rule in rules:
            rule_id, rule_type, category_id, rule_content_str, priority = rule
            try:
                rule_content = json.loads(rule_content_str)
            except Exception:
                continue

            matched = False
            if rule_type == "extension":
                matched = (extension or "").lower() == rule_content.get("value", "").lower()
            elif rule_type == "filename_pattern":
                pattern = rule_content.get("pattern", "")
                matched = bool(re.search(pattern, file_name or "", re.IGNORECASE))
            elif rule_type == "metadata_field":
                field = rule_content.get("field", "")
                value = rule_content.get("value", "")
                if field == "artist_lang":
                    matched = artist_lang == value
                else:
                    matched = meta.get(field) == value
            elif rule_type == "folder_path":
                pattern = rule_content.get("pattern", "")
                matched = bool(re.search(pattern, file_path or "", re.IGNORECASE))

            if matched:
                # hit_count 증가
                self.db.execute(text(
                    "UPDATE fc_rules SET hit_count = hit_count + 1 WHERE id = :id"
                ), {"id": rule_id})
                return category_id

        return None
