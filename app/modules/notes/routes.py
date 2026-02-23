"""Notes API 라우트 — 16개 엔드포인트.

⚠️ 라우트 순서 중요:
  /archive, /tags 를 /{id} 보다 먼저 정의해야 FastAPI가 올바르게 매칭함.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.notes import services as svc
from app.modules.notes.services import _note_to_dict, _archive_to_dict
from app.modules.notes.schemas import (
    NoteCreate, NoteUpdate,
    NoteListResponse, NoteResponse,
    NoteArchiveResponse, ArchiveListResponse,
    TagCreate, TagUpdate, TagResponse,
    HistoryResponse,
    BulkNoteIds, BulkTagAction, BulkStarAction,
)

router = APIRouter(prefix="/api/notes", tags=["Notes"])


# ══════════════════════════════════════════
# Bulk 라우트 (⚠️ /{note_id} 보다 먼저 정의)
# ══════════════════════════════════════════

@router.post("/bulk/delete")
def bulk_delete(data: BulkNoteIds, db: Session = Depends(get_db)):
    """여러 메모 일괄 삭제 (soft delete)."""
    count = svc.bulk_delete(db, data.note_ids)
    return {"ok": True, "count": count}


@router.post("/bulk/archive")
def bulk_archive(data: BulkNoteIds, db: Session = Depends(get_db)):
    """여러 메모 일괄 아카이브."""
    count = svc.bulk_archive(db, data.note_ids)
    return {"ok": True, "count": count}


@router.post("/bulk/tag")
def bulk_tag(data: BulkTagAction, db: Session = Depends(get_db)):
    """여러 메모에 태그 일괄 추가/제거."""
    count = svc.bulk_tag(db, data.note_ids, data.add_tag_ids, data.remove_tag_ids)
    return {"ok": True, "count": count}


@router.post("/bulk/star")
def bulk_star(data: BulkStarAction, db: Session = Depends(get_db)):
    """여러 메모 별표 일괄 설정."""
    count = svc.bulk_star(db, data.note_ids, data.starred)
    return {"ok": True, "count": count}


# ══════════════════════════════════════════
# Archive 라우트 (⚠️ /{id} 보다 먼저 정의)
# ══════════════════════════════════════════

@router.get("/archive", response_model=ArchiveListResponse)
def get_archive_list(
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """아카이브 메모 목록 조회."""
    return svc.list_archive(db, tag=tag, page=page, page_size=page_size)


@router.get("/archive/{archive_id}", response_model=NoteArchiveResponse)
def get_archive_item(archive_id: int, db: Session = Depends(get_db)):
    """아카이브 메모 상세 조회."""
    archive = svc.get_archive(db, archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="아카이브를 찾을 수 없습니다.")
    return _archive_to_dict(archive)


@router.post("/archive/{archive_id}/restore", response_model=NoteResponse)
def restore_archive(archive_id: int, db: Session = Depends(get_db)):
    """아카이브 복원 → 활성 메모로."""
    note = svc.restore_archive(db, archive_id)
    return _note_to_dict(note)


@router.delete("/archive/{archive_id}")
def delete_archive(archive_id: int, db: Session = Depends(get_db)):
    """아카이브 영구 삭제."""
    svc.delete_archive(db, archive_id)
    return {"ok": True}


# ══════════════════════════════════════════
# Tags 라우트 (⚠️ /{id} 보다 먼저 정의)
# ══════════════════════════════════════════

@router.get("/tags", response_model=list[TagResponse])
def get_tags(db: Session = Depends(get_db)):
    """태그 목록 (메모 수 포함)."""
    return svc.list_tags(db)


@router.post("/tags", response_model=TagResponse, status_code=201)
def create_tag(data: TagCreate, db: Session = Depends(get_db)):
    """태그 생성."""
    return svc.create_tag(db, name=data.name, color=data.color)


@router.put("/tags/{tag_id}", response_model=TagResponse)
def update_tag(tag_id: int, data: TagUpdate, db: Session = Depends(get_db)):
    """태그 수정."""
    return svc.update_tag(db, tag_id=tag_id, name=data.name, color=data.color)


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """태그 삭제 (CASCADE → note_tags 제거)."""
    svc.delete_tag(db, tag_id)
    return {"ok": True}


# ══════════════════════════════════════════
# Notes CRUD 라우트
# ══════════════════════════════════════════

@router.get("", response_model=NoteListResponse)
def get_notes(
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """메모 목록 조회 (태그/검색 필터, 페이지네이션)."""
    return svc.list_notes(db, tag=tag, search=search, page=page, page_size=page_size)


@router.post("", response_model=NoteResponse, status_code=201)
def create_note(data: NoteCreate, db: Session = Depends(get_db)):
    """메모 생성."""
    note = svc.create_note(
        db,
        title=data.title,
        content=data.content,
        remark=data.remark,
        tag_ids=data.tag_ids,
    )
    return _note_to_dict(note)


@router.get("/{note_id}", response_model=NoteResponse)
def get_note(note_id: int, db: Session = Depends(get_db)):
    """메모 상세 조회."""
    note = svc.get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")
    return _note_to_dict(note)


@router.put("/{note_id}", response_model=NoteResponse)
def update_note(note_id: int, data: NoteUpdate, db: Session = Depends(get_db)):
    """메모 수정 (변경 전 스냅샷 자동 저장)."""
    note = svc.update_note(
        db,
        note_id=note_id,
        title=data.title,
        content=data.content,
        remark=data.remark,
        tag_ids=data.tag_ids,
    )
    return _note_to_dict(note)


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    hard: bool = Query(False),
    db: Session = Depends(get_db),
):
    """메모 삭제. hard=false(기본): soft delete, hard=true: 영구 삭제."""
    svc.delete_note(db, note_id, hard=hard)
    return {"ok": True}


@router.post("/{note_id}/pin", response_model=NoteResponse)
def toggle_pin(note_id: int, db: Session = Depends(get_db)):
    """메모 고정/고정해제 토글."""
    note = svc.toggle_pin(db, note_id)
    return _note_to_dict(note)


@router.post("/{note_id}/archive", response_model=NoteArchiveResponse)
def archive_note(note_id: int, db: Session = Depends(get_db)):
    """메모 아카이브 이동 (태그·이력 함께 이전)."""
    archive = svc.archive_note(db, note_id)
    return _archive_to_dict(archive)


# ══════════════════════════════════════════
# History 라우트
# ══════════════════════════════════════════

@router.get("/{note_id}/history", response_model=list[HistoryResponse])
def get_history(note_id: int, db: Session = Depends(get_db)):
    """메모 수정 이력 목록."""
    note = svc.get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")
    return svc.get_history(db, note_id)
