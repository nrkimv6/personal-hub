"""옵시디언 노트 관련 API"""
import json
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from ..database import get_db, SessionLocal
from ..config import settings
from ..workers.obsidian.scanner import ObsidianScanner
from ..workers.obsidian.classifier import ObsidianClassifier
from ..workers.obsidian.extractor import ObsidianExtractor

router = APIRouter()

# 스캔 상태
_obsidian_scan_state = {"status": "idle", "total": 0, "processed": 0, "current": ""}
_obsidian_scanner = None

# 분류 상태
_classify_state = {"status": "idle", "total": 0, "processed": 0}
_classifier = None

# 추출 상태
_extract_state = {"status": "idle", "total": 0, "processed": 0}
_extractor = None


@router.post("/obsidian/scan/start")
async def obsidian_scan_start(
    background_tasks: BackgroundTasks,
    vault_path: Optional[str] = None,
    db: Session = Depends(get_db)
):
    global _obsidian_scanner, _obsidian_scan_state
    if _obsidian_scan_state["status"] == "running":
        return {"message": "이미 스캔 중입니다."}

    path = vault_path or settings.OBSIDIAN_VAULT_PATH
    if not path:
        return {"error": "OBSIDIAN_VAULT_PATH가 설정되지 않았습니다."}

    _obsidian_scan_state = {"status": "running", "total": 0, "processed": 0, "current": ""}

    def run_scan():
        global _obsidian_scanner, _obsidian_scan_state
        scan_db = SessionLocal()
        try:
            scanner = ObsidianScanner(scan_db)
            _obsidian_scanner = scanner

            def callback(processed, total, current):
                _obsidian_scan_state.update({"processed": processed, "total": total, "current": current})

            result = scanner.scan(path, progress_callback=callback)
            _obsidian_scan_state["status"] = "completed"
            _obsidian_scan_state.update(result)
        finally:
            scan_db.close()

    background_tasks.add_task(run_scan)
    return {"message": "스캔을 시작합니다."}


@router.post("/obsidian/scan/stop")
async def obsidian_scan_stop():
    global _obsidian_scanner
    if _obsidian_scanner:
        _obsidian_scanner.stop()
        _obsidian_scan_state["status"] = "stopped"
    return {"message": "스캔 중지 요청됨"}


@router.get("/obsidian/scan/status")
async def obsidian_scan_status():
    return _obsidian_scan_state


@router.get("/obsidian/stats")
async def obsidian_stats(db: Session = Depends(get_db)):
    total = db.execute(text("SELECT COUNT(*) FROM obsidian_notes")).scalar()
    avg_length = db.execute(text("SELECT AVG(content_length) FROM obsidian_notes")).scalar()
    fm_count = db.execute(text("SELECT COUNT(*) FROM obsidian_notes WHERE has_frontmatter = 1")).scalar()
    daily_count = db.execute(text("SELECT COUNT(*) FROM obsidian_notes WHERE is_daily_note = 1")).scalar()

    # 태그 TOP 20
    tag_counter = {}
    rows = db.execute(text("SELECT tags_json FROM obsidian_notes WHERE tags_json IS NOT NULL")).fetchall()
    for row in rows:
        try:
            tags = json.loads(row[0])
            for tag in tags:
                tag_counter[tag] = tag_counter.get(tag, 0) + 1
        except Exception:
            pass
    top_tags = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)[:20]

    # 링크 TOP 20
    link_counter = {}
    rows = db.execute(text("SELECT links_json FROM obsidian_notes WHERE links_json IS NOT NULL")).fetchall()
    for row in rows:
        try:
            links = json.loads(row[0])
            for link in links:
                link_counter[link] = link_counter.get(link, 0) + 1
        except Exception:
            pass
    top_links = sorted(link_counter.items(), key=lambda x: x[1], reverse=True)[:20]

    return {
        "total": total or 0,
        "avg_content_length": round(avg_length or 0),
        "frontmatter_ratio": round((fm_count or 0) / max(total or 1, 1) * 100, 1),
        "daily_notes_count": daily_count or 0,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "top_links": [{"link": l, "count": c} for l, c in top_links],
    }


@router.get("/obsidian/notes")
async def obsidian_notes(
    note_type: Optional[str] = None,
    is_daily: Optional[bool] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    where_clauses = []
    params: dict = {"skip": skip, "limit": limit}
    if note_type:
        where_clauses.append("note_type = :note_type")
        params["note_type"] = note_type
    if is_daily is not None:
        where_clauses.append("is_daily_note = :is_daily")
        params["is_daily"] = is_daily
    if search:
        where_clauses.append("(file_name LIKE :search OR file_path LIKE :search)")
        params["search"] = f"%{search}%"

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total = db.execute(text(f"SELECT COUNT(*) FROM obsidian_notes {where_sql}"), params).scalar()
    rows = db.execute(text(
        f"SELECT id, file_path, file_name, content_length, note_type, is_daily_note, "
        f"has_frontmatter, status FROM obsidian_notes {where_sql} "
        f"ORDER BY file_modified_at DESC LIMIT :limit OFFSET :skip"
    ), params).fetchall()

    return {
        "total": total,
        "items": [dict(zip(
            ["id", "file_path", "file_name", "content_length", "note_type", "is_daily_note", "has_frontmatter", "status"],
            row
        )) for row in rows]
    }


@router.post("/obsidian/classify/sample")
async def obsidian_classify_sample(
    sample_size: int = 30,
    db: Session = Depends(get_db)
):
    """랜덤 샘플 30개 LLM 분류 (분류 기준 초안 확정용)"""
    import subprocess

    rows = db.execute(text(
        "SELECT id, file_name, content_length, frontmatter_json FROM obsidian_notes "
        "WHERE status = 'scanned' ORDER BY RANDOM() LIMIT :n"
    ), {"n": sample_size}).fetchall()

    results = []
    for row in rows:
        note_id, fname, length, fm_json = row
        fm = {}
        try:
            fm = json.loads(fm_json) if fm_json else {}
        except Exception:
            pass

        prompt = f"""노트를 분류하세요.
파일명: {fname}
글자수: {length}
frontmatter: {json.dumps(fm, ensure_ascii=False)[:100]}

분류: memo(짧고 비정형) / record(길고 구조적) / daily(날짜기반) / other
JSON 응답: {{"note_type": "...", "confidence": 0.0~1.0}}"""

        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                content = data.get("result", data.get("content", "{}"))
                classified = json.loads(content) if isinstance(content, str) else content
                results.append({"note_id": note_id, "file_name": fname, **classified})
            else:
                results.append({"note_id": note_id, "file_name": fname, "note_type": "unknown", "error": result.stderr})
        except Exception as e:
            results.append({"note_id": note_id, "file_name": fname, "note_type": "unknown", "error": str(e)})

    return {"sample_count": len(results), "results": results}


@router.post("/obsidian/classify/start")
async def obsidian_classify_start(
    background_tasks: BackgroundTasks,
    use_llm: bool = True,
    db: Session = Depends(get_db)
):
    global _classifier, _classify_state
    if _classify_state["status"] == "running":
        return {"message": "이미 분류 중입니다."}

    _classify_state = {"status": "running", "total": 0, "processed": 0}

    def run_classify():
        global _classifier, _classify_state
        cls_db = SessionLocal()
        try:
            classifier = ObsidianClassifier(cls_db)
            _classifier = classifier

            def callback(processed, total, current):
                _classify_state.update({"processed": processed, "total": total})

            result = classifier.classify(use_llm=use_llm, progress_callback=callback)
            _classify_state["status"] = "completed"
            _classify_state.update(result)
        finally:
            cls_db.close()

    background_tasks.add_task(run_classify)
    return {"message": "분류를 시작합니다."}


@router.get("/obsidian/classify/status")
async def obsidian_classify_status():
    return _classify_state


@router.post("/obsidian/classify/approve")
async def obsidian_classify_approve(
    note_ids: List[int],
    note_type: str,
    db: Session = Depends(get_db)
):
    """일괄 승인 — 선택한 노트들의 note_type을 업데이트하고 status를 reviewed로 변경"""
    if note_type not in ("memo", "record", "daily", "other"):
        return {"error": f"유효하지 않은 note_type: {note_type}"}

    updated = 0
    for note_id in note_ids:
        db.execute(text(
            "UPDATE obsidian_notes SET note_type = :t, status = 'reviewed' WHERE id = :id"
        ), {"t": note_type, "id": note_id})
        updated += 1

    db.commit()
    return {"updated": updated}


@router.post("/obsidian/extract/start")
async def obsidian_extract_start(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    global _extractor, _extract_state
    if _extract_state["status"] == "running":
        return {"message": "이미 추출 중입니다."}

    _extract_state = {"status": "running", "total": 0, "processed": 0}

    def run_extract():
        global _extractor, _extract_state
        ext_db = SessionLocal()
        try:
            extractor = ObsidianExtractor(ext_db)
            _extractor = extractor

            def callback(processed, total, current):
                _extract_state.update({"processed": processed, "total": total})

            result = extractor.extract(progress_callback=callback)
            _extract_state["status"] = "completed"
            _extract_state.update(result)
        finally:
            ext_db.close()

    background_tasks.add_task(run_extract)
    return {"message": "추출을 시작합니다."}


@router.get("/obsidian/extract/status")
async def obsidian_extract_status():
    return _extract_state


@router.get("/obsidian/extract/results")
async def obsidian_extract_results(
    note_type_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """extracted_json이 있는 노트 목록 반환"""
    where_clauses = ["extracted_json IS NOT NULL"]
    params: dict = {"skip": skip, "limit": limit}

    if note_type_filter:
        where_clauses.append("note_type = :note_type_filter")
        params["note_type_filter"] = note_type_filter

    where_sql = "WHERE " + " AND ".join(where_clauses)

    total = db.execute(text(f"SELECT COUNT(*) FROM obsidian_notes {where_sql}"), params).scalar()
    rows = db.execute(text(
        f"SELECT id, file_name, note_type, extracted_json FROM obsidian_notes {where_sql} "
        f"ORDER BY file_modified_at DESC LIMIT :limit OFFSET :skip"
    ), params).fetchall()

    items = []
    for row in rows:
        note_id, fname, ntype, ext_json = row
        extracted = {}
        try:
            extracted = json.loads(ext_json) if ext_json else {}
        except Exception:
            pass
        items.append({"id": note_id, "file_name": fname, "note_type": ntype, "extracted": extracted})

    return {"total": total, "items": items}


@router.get("/obsidian/extract/export")
async def obsidian_extract_export(db: Session = Depends(get_db)):
    """전체 추출 결과 JSON 반환"""
    rows = db.execute(text(
        "SELECT id, file_name, file_path, note_type, extracted_json "
        "FROM obsidian_notes WHERE extracted_json IS NOT NULL"
    )).fetchall()

    export_data = []
    for row in rows:
        note_id, fname, fpath, ntype, ext_json = row
        extracted = {}
        try:
            extracted = json.loads(ext_json) if ext_json else {}
        except Exception:
            pass
        export_data.append({
            "id": note_id,
            "file_name": fname,
            "file_path": fpath,
            "note_type": ntype,
            "extracted": extracted
        })

    return JSONResponse(content={"total": len(export_data), "data": export_data})
