"""문서 파일 메타데이터 추출 (확장자 기반)"""
import json
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


_DOC_TYPE_MAP = {
    '.pdf': 'pdf',
    '.doc': 'office', '.docx': 'office',
    '.xls': 'office', '.xlsx': 'office',
    '.ppt': 'office', '.pptx': 'office',
    '.hwp': 'office', '.hwpx': 'office',
    '.txt': 'text', '.md': 'text', '.rtf': 'text',
    '.html': 'text', '.htm': 'text', '.mhtml': 'text',
    '.ics': 'calendar',
}


def extract(file_id: int, file_path: str, db: Session) -> dict:
    ext = Path(file_path).suffix.lower()
    doc_type = _DOC_TYPE_MAP.get(ext, 'other')

    meta = {"type": doc_type, "extension": ext}

    try:
        size = Path(file_path).stat().st_size
        meta["size_bytes"] = size
    except Exception:
        pass

    try:
        db.execute(text(
            "UPDATE fc_files SET metadata_json = :meta WHERE id = :id"
        ), {"meta": json.dumps(meta), "id": file_id})
    except Exception as e:
        return {"error": str(e)}

    return meta
