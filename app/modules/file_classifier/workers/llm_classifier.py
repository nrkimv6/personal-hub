"""LLM 폴백 분류기"""
import json
import subprocess
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Callable
from pathlib import Path


class LLMClassifier:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def classify(self, task_id=None, progress_callback=None) -> dict:
        stats = {"total": 0, "classified": 0, "errors": 0}

        # 미분류 파일 (metadata_extracted 상태이고 rule_category_id 없는 것)
        files = self.db.execute(text(
            "SELECT f.id, f.file_path, f.file_name, f.extension, f.file_group, f.file_size, "
            "f.metadata_json FROM fc_files f "
            "WHERE f.status IN ('pending', 'metadata_extracted') AND f.rule_category_id IS NULL"
        )).fetchall()

        # 카테고리 목록
        categories = self.db.execute(text(
            "SELECT full_path FROM fc_categories ORDER BY full_path"
        )).fetchall()
        category_list = [r[0] for r in categories]

        stats["total"] = len(files)
        for file_row in files:
            if self._stop_flag:
                break
            try:
                result = self._classify_one(file_row, category_list)
                if result:
                    cat_id = self.db.execute(text(
                        "SELECT id FROM fc_categories WHERE full_path = :p"
                    ), {"p": result["category"]}).fetchone()
                    if cat_id:
                        self.db.execute(text(
                            "UPDATE fc_files SET llm_category_id = :cat_id, "
                            "llm_confidence = :conf, llm_reasoning = :reason, "
                            "status = 'llm_classified', classified_at = CURRENT_TIMESTAMP "
                            "WHERE id = :id"
                        ), {"cat_id": cat_id[0], "conf": result.get("confidence", 0.5),
                            "reason": result.get("reasoning", ""), "id": file_row[0]})
                        self.db.commit()
                        stats["classified"] += 1
            except Exception as e:
                stats["errors"] += 1

        return stats

    def _classify_one(self, file_row, category_list) -> Optional[dict]:
        file_id, file_path, file_name, extension, file_group, file_size, metadata_json = file_row

        # 상위 3단계 폴더 경로
        parts = Path(file_path).parts
        folder_context = "/".join(parts[-4:-1]) if len(parts) >= 4 else str(Path(file_path).parent)

        meta = json.loads(metadata_json) if metadata_json else {}
        size_mb = round((file_size or 0) / 1024 / 1024, 1)

        prompt = f"""파일을 분류하세요.

파일명: {file_name}
확장자: {extension}
그룹: {file_group}
크기: {size_mb}MB
폴더: {folder_context}
메타데이터: {json.dumps(meta, ensure_ascii=False)[:200]}

카테고리 목록:
{chr(10).join(category_list[:30])}

JSON으로 응답: {{"category": "카테고리/경로", "confidence": 0.0~1.0, "reasoning": "이유"}}"""

        from ..config import settings
        if settings.LLM_MODE == "cli":
            try:
                result = subprocess.run(
                    ["claude", "-p", prompt, "--output-format", "json"],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    text_out = data.get("result", data.get("content", result.stdout))
                    if isinstance(text_out, str):
                        return json.loads(text_out)
                    return text_out
            except Exception:
                pass
        return None
