"""옵시디언 vault .md 파일 스캔 및 파싱"""
import re
import json
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Callable

# Daily Note 패턴 (YYYY-MM-DD.md)
DAILY_NOTE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')
# 태그 패턴 (#태그)
TAG_PATTERN = re.compile(r'(?<!\S)#([a-zA-Z가-힣0-9_/-]+)')
# 위키링크 패턴 ([[링크]])
WIKILINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')

# 제외 폴더
EXCLUDE_DIRS = {'.obsidian', '.smart-env', '.claude', '.git', '__pycache__'}

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """YAML frontmatter 파싱 → (dict, 본문)"""
    if not content.startswith('---'):
        return {}, content
    end_idx = content.find('---', 3)
    if end_idx == -1:
        return {}, content

    fm_text = content[3:end_idx].strip()
    body = content[end_idx + 3:].strip()

    fm = {}
    for line in fm_text.splitlines():
        if ':' in line:
            key, _, val = line.partition(':')
            fm[key.strip()] = val.strip()
    return fm, body

class ObsidianScanner:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def scan(self, vault_path: str, task_id: Optional[int] = None,
             progress_callback: Optional[Callable] = None) -> dict:
        stats = {"total": 0, "inserted": 0, "errors": 0}
        vault = Path(vault_path)
        if not vault.exists():
            return {"error": f"Vault not found: {vault_path}"}

        # .md 파일 수집 (제외 폴더 스킵)
        md_files = []
        for md_file in vault.rglob('*.md'):
            if self._stop_flag:
                break
            # 제외 폴더 확인
            if any(part in EXCLUDE_DIRS for part in md_file.parts):
                continue
            md_files.append(md_file)

        stats["total"] = len(md_files)

        for i, md_file in enumerate(md_files):
            if self._stop_flag:
                break
            try:
                self._process_file(md_file)
                stats["inserted"] += 1
            except Exception as e:
                stats["errors"] += 1

            if (i + 1) % 50 == 0 and progress_callback:
                progress_callback(i + 1, stats["total"], str(md_file))

        return stats

    def _process_file(self, md_file: Path):
        try:
            content = md_file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            content = ""

        stat = md_file.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat()

        frontmatter, body = parse_frontmatter(content)
        has_frontmatter = bool(frontmatter)
        content_length = len(body)
        is_daily_note = bool(DAILY_NOTE_PATTERN.match(md_file.name))

        tags = list(set(TAG_PATTERN.findall(content)))
        links = list(set(WIKILINK_PATTERN.findall(content)))

        self.db.execute(text("""
            INSERT OR REPLACE INTO obsidian_notes
                (file_path, file_name, file_size, file_modified_at,
                 has_frontmatter, frontmatter_json, content_length,
                 tags_json, links_json, is_daily_note, status)
            VALUES
                (:file_path, :file_name, :file_size, :file_modified_at,
                 :has_frontmatter, :frontmatter_json, :content_length,
                 :tags_json, :links_json, :is_daily_note, 'scanned')
        """), {
            "file_path": str(md_file),
            "file_name": md_file.name,
            "file_size": stat.st_size,
            "file_modified_at": modified_at,
            "has_frontmatter": has_frontmatter,
            "frontmatter_json": json.dumps(frontmatter, ensure_ascii=False),
            "content_length": content_length,
            "tags_json": json.dumps(tags, ensure_ascii=False),
            "links_json": json.dumps(links, ensure_ascii=False),
            "is_daily_note": is_daily_note,
        })
        self.db.commit()
