"""압축 파일 메타데이터 추출 (zipfile/py7zr)"""
import json
import threading
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


def extract(file_id: int, file_path: str, db: Session) -> dict:
    ext = Path(file_path).suffix.lower()
    result = {"file_count": 0, "is_encrypted": False}
    contents = []

    try:
        file_list = _extract_with_timeout(file_path, ext, timeout=10)
        if file_list is None:
            return {"file_count": 0, "is_encrypted": False, "error": "timeout"}

        is_encrypted = file_list.get("is_encrypted", False)
        entries = file_list.get("entries", [])
        result = {"file_count": len(entries), "is_encrypted": is_encrypted}
        contents = entries
    except Exception as e:
        result["error"] = str(e)
        return result

    # fc_archive_contents INSERT
    try:
        for entry in contents[:200]:  # 최대 200개
            db.execute(text("""
                INSERT OR IGNORE INTO fc_archive_contents
                    (file_id, inner_path, inner_size, is_encrypted)
                VALUES (:file_id, :inner_path, :inner_size, :is_encrypted)
            """), {
                "file_id": file_id,
                "inner_path": entry.get("name", ""),
                "inner_size": entry.get("size", 0),
                "is_encrypted": is_encrypted
            })

        # fc_files metadata_json 업데이트
        meta = {"file_count": result["file_count"], "is_encrypted": is_encrypted}
        db.execute(text(
            "UPDATE fc_files SET metadata_json = :meta WHERE id = :id"
        ), {"meta": json.dumps(meta), "id": file_id})
    except Exception as e:
        result["db_error"] = str(e)

    return result


def _extract_with_timeout(file_path: str, ext: str, timeout: int) -> dict:
    result_holder = [None]
    exc_holder = [None]

    def worker():
        try:
            result_holder[0] = _do_extract(file_path, ext)
        except Exception as e:
            exc_holder[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        return None  # timeout
    if exc_holder[0]:
        raise exc_holder[0]
    return result_holder[0]


def _do_extract(file_path: str, ext: str) -> dict:
    if ext == ".zip":
        import zipfile
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                entries = []
                is_encrypted = False
                for info in zf.infolist():
                    if info.flag_bits & 0x1:
                        is_encrypted = True
                    entries.append({"name": info.filename, "size": info.file_size})
                return {"entries": entries, "is_encrypted": is_encrypted}
        except zipfile.BadZipFile:
            return {"entries": [], "is_encrypted": False}

    elif ext == ".7z":
        try:
            import py7zr
            with py7zr.SevenZipFile(file_path, mode='r') as zf:
                entries = []
                for fname, finfo in zf.files.items() if hasattr(zf, 'files') else []:
                    entries.append({"name": fname, "size": getattr(finfo, 'uncompressed', 0)})
                if not entries:
                    # fallback: list method
                    with py7zr.SevenZipFile(file_path, mode='r') as zf2:
                        for item in zf2.list():
                            entries.append({"name": item.filename, "size": item.uncompressed or 0})
                return {"entries": entries, "is_encrypted": False}
        except Exception:
            return {"entries": [], "is_encrypted": False}

    elif ext == ".rar":
        try:
            import rarfile
            with rarfile.RarFile(file_path) as rf:
                entries = []
                is_encrypted = rf.needs_password()
                for info in rf.infolist():
                    entries.append({"name": info.filename, "size": info.file_size})
                return {"entries": entries, "is_encrypted": is_encrypted}
        except Exception:
            return {"entries": [], "is_encrypted": False}

    return {"entries": [], "is_encrypted": False}
