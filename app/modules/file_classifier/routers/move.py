"""파일 이동 API"""
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db, SessionLocal
from ..workers.mover import MoveManager

router = APIRouter(tags=["File Classifier - Move"])


class MoveRequest(BaseModel):
    file_ids: Optional[List[int]] = None


@router.post("/move/preview")
async def move_preview(request: MoveRequest, db: Session = Depends(get_db)):
    """이동 미리보기 (dry-run)"""
    manager = MoveManager(db)
    results = manager.preview(request.file_ids)
    return {"status": "ok", "count": len(results), "items": results}


@router.post("/move/execute")
async def move_execute(request: MoveRequest, db: Session = Depends(get_db)):
    """실제 파일 이동"""
    manager = MoveManager(db)
    stats = manager.execute(request.file_ids)
    return {"status": "ok", **stats}


@router.post("/move/undo/{file_id}")
async def move_undo(file_id: int, db: Session = Depends(get_db)):
    """파일 이동 되돌리기"""
    manager = MoveManager(db)
    success = manager.undo(file_id)
    return {"status": "ok" if success else "failed", "file_id": file_id}


@router.get("/move/status")
async def move_status(db: Session = Depends(get_db)):
    """이동 통계"""
    moved = db.execute(text("SELECT COUNT(*) FROM fc_files WHERE status = 'moved'")).scalar()
    pending = db.execute(text("SELECT COUNT(*) FROM fc_files WHERE status = 'approved'")).scalar()
    return {"moved": moved, "pending_move": pending}
