"""Notes 서비스 — CRUD, Archive, Tags."""

import math
from datetime import datetime
from typing import Optional, List

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.modules.notes.models import Note, NoteArchive, NoteTag, NoteTagDef, NoteHistory


# ──────────────── 내부 헬퍼 ────────────────

def _tag_info(tag: NoteTag) -> dict:
    return {"id": tag.tag_def.id, "name": tag.tag_def.name, "color": tag.tag_def.color}


def _note_to_dict(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "remark": note.remark,
        "is_pinned": bool(note.is_pinned),
        "tags": [_tag_info(t) for t in note.tags],
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


def _archive_to_dict(archive: NoteArchive) -> dict:
    return {
        "id": archive.id,
        "original_id": archive.original_id,
        "title": archive.title,
        "content": archive.content,
        "remark": archive.remark,
        "tags": [_tag_info(t) for t in archive.tags],
        "created_at": archive.created_at,
        "updated_at": archive.updated_at,
        "archived_at": archive.archived_at,
    }


def _validate_tag_ids(db: Session, tag_ids: List[int]) -> None:
    """존재하지 않는 tag_id가 있으면 400 에러."""
    if not tag_ids:
        return
    existing = db.query(NoteTagDef.id).filter(NoteTagDef.id.in_(tag_ids)).all()
    existing_ids = {r.id for r in existing}
    missing = set(tag_ids) - existing_ids
    if missing:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 tag_id: {sorted(missing)}")


def _set_tags(db: Session, note_id: int, tag_ids: List[int], source: str = "note") -> None:
    """해당 note의 기존 태그 삭제 후 새로 삽입."""
    db.query(NoteTag).filter(
        and_(NoteTag.note_id == note_id, NoteTag.source == source)
    ).delete(synchronize_session=False)
    for tid in tag_ids:
        db.add(NoteTag(note_id=note_id, tag_id=tid, source=source))


# ──────────────── Notes CRUD ────────────────

def list_notes(
    db: Session,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(Note).filter(Note.deleted_at.is_(None))

    if tag:
        query = query.join(
            NoteTag, and_(NoteTag.note_id == Note.id, NoteTag.source == "note")
        ).join(NoteTagDef, NoteTagDef.id == NoteTag.tag_id).filter(NoteTagDef.name == tag)

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(
            Note.title.ilike(pattern) | Note.content.ilike(pattern)
        )

    total = query.count()
    pages = max(1, math.ceil(total / page_size))
    items = (
        query.order_by(Note.is_pinned.desc(), Note.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_note_to_dict(n) for n in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def get_note(db: Session, note_id: int) -> Optional[Note]:
    return db.query(Note).filter(Note.id == note_id, Note.deleted_at.is_(None)).first()


def create_note(
    db: Session,
    title: str,
    content: str = "",
    remark: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
) -> Note:
    tag_ids = tag_ids or []
    _validate_tag_ids(db, tag_ids)

    note = Note(title=title, content=content, remark=remark)
    db.add(note)
    db.flush()  # id 확보

    _set_tags(db, note.id, tag_ids, source="note")
    db.commit()
    db.refresh(note)
    return note


def update_note(
    db: Session,
    note_id: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
    remark: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
) -> Note:
    note = get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")

    # 변경 전 스냅샷 저장
    history = NoteHistory(
        note_id=note.id,
        source="note",
        title=note.title,
        content=note.content,
        remark=note.remark,
    )
    db.add(history)

    if title is not None:
        note.title = title
    if content is not None:
        note.content = content
    if remark is not None:
        note.remark = remark
    note.updated_at = datetime.utcnow()

    if tag_ids is not None:
        _validate_tag_ids(db, tag_ids)
        _set_tags(db, note.id, tag_ids, source="note")

    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, note_id: int, hard: bool = False) -> bool:
    note = get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")

    if hard:
        db.delete(note)
    else:
        note.deleted_at = datetime.utcnow()

    db.commit()
    return True


def toggle_pin(db: Session, note_id: int) -> Note:
    note = get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")

    note.is_pinned = 0 if note.is_pinned else 1
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return note


# ──────────────── Archive & History ────────────────

def archive_note(db: Session, note_id: int) -> NoteArchive:
    note = get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")

    archive = NoteArchive(
        original_id=note.id,
        title=note.title,
        content=note.content,
        remark=note.remark,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )
    db.add(archive)
    db.flush()

    # NoteTag 이전: source='note' → 'archive', note_id → archive.id
    note_tags = db.query(NoteTag).filter(
        NoteTag.note_id == note.id, NoteTag.source == "note"
    ).all()
    for nt in note_tags:
        nt.note_id = archive.id
        nt.source = "archive"

    # NoteHistory 이전: source='note' → 'archive', note_id → archive.id
    histories = db.query(NoteHistory).filter(
        NoteHistory.note_id == note.id, NoteHistory.source == "note"
    ).all()
    for h in histories:
        h.note_id = archive.id
        h.source = "archive"

    db.delete(note)
    db.commit()
    db.refresh(archive)
    return archive


def list_archive(
    db: Session,
    tag: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(NoteArchive)

    if tag:
        query = query.join(
            NoteTag, and_(NoteTag.note_id == NoteArchive.id, NoteTag.source == "archive")
        ).join(NoteTagDef, NoteTagDef.id == NoteTag.tag_id).filter(NoteTagDef.name == tag)

    total = query.count()
    pages = max(1, math.ceil(total / page_size))
    items = (
        query.order_by(NoteArchive.archived_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_archive_to_dict(a) for a in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def get_archive(db: Session, archive_id: int) -> Optional[NoteArchive]:
    return db.query(NoteArchive).filter(NoteArchive.id == archive_id).first()


def restore_archive(db: Session, archive_id: int) -> Note:
    archive = get_archive(db, archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="아카이브를 찾을 수 없습니다.")

    note = Note(
        title=archive.title,
        content=archive.content,
        remark=archive.remark,
        created_at=archive.created_at,
        updated_at=archive.updated_at,
    )
    db.add(note)
    db.flush()

    # NoteTag 복원: source='archive' → 'note', note_id → note.id
    archive_tags = db.query(NoteTag).filter(
        NoteTag.note_id == archive.id, NoteTag.source == "archive"
    ).all()
    for nt in archive_tags:
        nt.note_id = note.id
        nt.source = "note"

    # NoteHistory 복원: source='archive' → 'note', note_id → note.id
    histories = db.query(NoteHistory).filter(
        NoteHistory.note_id == archive.id, NoteHistory.source == "archive"
    ).all()
    for h in histories:
        h.note_id = note.id
        h.source = "note"

    db.delete(archive)
    db.commit()
    db.refresh(note)
    return note


def delete_archive(db: Session, archive_id: int) -> bool:
    archive = get_archive(db, archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="아카이브를 찾을 수 없습니다.")

    # 연결 태그 삭제
    db.query(NoteTag).filter(
        NoteTag.note_id == archive.id, NoteTag.source == "archive"
    ).delete(synchronize_session=False)

    # 연결 이력 삭제
    db.query(NoteHistory).filter(
        NoteHistory.note_id == archive.id, NoteHistory.source == "archive"
    ).delete(synchronize_session=False)

    db.delete(archive)
    db.commit()
    return True


def get_history(db: Session, note_id: int) -> List[NoteHistory]:
    return (
        db.query(NoteHistory)
        .filter(NoteHistory.note_id == note_id, NoteHistory.source == "note")
        .order_by(NoteHistory.changed_at.desc())
        .all()
    )


# ──────────────── Tags ────────────────

def list_tags(db: Session) -> List[dict]:
    tags = db.query(NoteTagDef).order_by(NoteTagDef.name).all()
    result = []
    for tag in tags:
        count = db.query(NoteTag).filter(
            NoteTag.tag_id == tag.id, NoteTag.source == "note"
        ).count()
        result.append({
            "id": tag.id,
            "name": tag.name,
            "color": tag.color,
            "note_count": count,
            "created_at": tag.created_at,
        })
    return result


def create_tag(db: Session, name: str, color: Optional[str] = None) -> NoteTagDef:
    existing = db.query(NoteTagDef).filter(NoteTagDef.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"이미 존재하는 태그 이름입니다: {name}")

    tag = NoteTagDef(name=name, color=color or "#6b7280")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(
    db: Session, tag_id: int, name: Optional[str] = None, color: Optional[str] = None
) -> NoteTagDef:
    tag = db.query(NoteTagDef).filter(NoteTagDef.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    if name is not None and name != tag.name:
        dup = db.query(NoteTagDef).filter(NoteTagDef.name == name).first()
        if dup:
            raise HTTPException(status_code=400, detail=f"이미 존재하는 태그 이름입니다: {name}")
        tag.name = name

    if color is not None:
        tag.color = color

    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag_id: int) -> bool:
    tag = db.query(NoteTagDef).filter(NoteTagDef.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    db.delete(tag)  # CASCADE로 NoteTag 삭제됨
    db.commit()
    return True
