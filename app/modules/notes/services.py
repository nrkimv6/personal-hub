"""Notes 서비스 — CRUD, Archive, Tags."""

import math
from datetime import datetime
from typing import Optional, List

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, distinct

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
    tags: Optional[List[str]] = None,
    tag_mode: str = "or",
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(Note).filter(Note.deleted_at.is_(None))

    # 하위호환: 단일 tag → tags 리스트로 변환
    effective_tags = tags
    if not effective_tags and tag:
        effective_tags = [tag]

    if effective_tags:
        query = query.join(
            NoteTag, and_(NoteTag.note_id == Note.id, NoteTag.source == "note")
        ).join(NoteTagDef, NoteTagDef.id == NoteTag.tag_id)

        if tag_mode == "and":
            # AND 모드: 모든 태그를 가진 메모만
            query = (
                query.filter(NoteTagDef.name.in_(effective_tags))
                .group_by(Note.id)
                .having(func.count(distinct(NoteTagDef.name)) == len(effective_tags))
            )
        else:
            # OR 모드: 태그 중 하나라도 가진 메모
            query = query.filter(NoteTagDef.name.in_(effective_tags)).distinct()

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(
            Note.title.ilike(pattern) | Note.content.ilike(pattern)
        )

    if date_from:
        query = query.filter(Note.created_at >= datetime.fromisoformat(date_from))

    if date_to:
        query = query.filter(Note.created_at <= datetime.fromisoformat(date_to))

    total = query.count()
    pages = max(1, math.ceil(total / page_size))

    # 정렬 컬럼 매핑 (허용 목록 외 기본값 적용)
    sort_columns = {
        "created_at": Note.created_at,
        "updated_at": Note.updated_at,
        "title": Note.title,
    }
    sort_col = sort_columns.get(sort, Note.created_at)
    sort_expr = sort_col.asc() if order == "asc" else sort_col.desc()

    items = (
        query.order_by(Note.is_pinned.desc(), sort_expr)
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

    # NoteTag 이전: 새로 생성 후 기존 삭제 (relationship 충돌 방지)
    note_tags = db.query(NoteTag).filter(
        NoteTag.note_id == note.id, NoteTag.source == "note"
    ).all()
    tag_ids = [nt.tag_id for nt in note_tags]
    db.query(NoteTag).filter(
        NoteTag.note_id == note.id, NoteTag.source == "note"
    ).delete(synchronize_session=False)
    for tid in tag_ids:
        db.add(NoteTag(note_id=archive.id, tag_id=tid, source="archive"))

    # NoteHistory 이전: 새로 생성 후 기존 삭제
    histories = db.query(NoteHistory).filter(
        NoteHistory.note_id == note.id, NoteHistory.source == "note"
    ).all()
    hist_data = [(h.title, h.content, h.remark, h.changed_at) for h in histories]
    db.query(NoteHistory).filter(
        NoteHistory.note_id == note.id, NoteHistory.source == "note"
    ).delete(synchronize_session=False)
    for title, content, remark, changed_at in hist_data:
        db.add(NoteHistory(
            note_id=archive.id, source="archive",
            title=title, content=content, remark=remark, changed_at=changed_at,
        ))

    db.expire(note)
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

    # NoteTag 복원: 새로 생성 후 기존 삭제
    archive_tags = db.query(NoteTag).filter(
        NoteTag.note_id == archive.id, NoteTag.source == "archive"
    ).all()
    tag_ids = [nt.tag_id for nt in archive_tags]
    db.query(NoteTag).filter(
        NoteTag.note_id == archive.id, NoteTag.source == "archive"
    ).delete(synchronize_session=False)
    for tid in tag_ids:
        db.add(NoteTag(note_id=note.id, tag_id=tid, source="note"))

    # NoteHistory 복원: 새로 생성 후 기존 삭제
    histories = db.query(NoteHistory).filter(
        NoteHistory.note_id == archive.id, NoteHistory.source == "archive"
    ).all()
    hist_data = [(h.title, h.content, h.remark, h.changed_at) for h in histories]
    db.query(NoteHistory).filter(
        NoteHistory.note_id == archive.id, NoteHistory.source == "archive"
    ).delete(synchronize_session=False)
    for title, content, remark, changed_at in hist_data:
        db.add(NoteHistory(
            note_id=note.id, source="note",
            title=title, content=content, remark=remark, changed_at=changed_at,
        ))

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


# ──────────────── Bulk 서비스 ────────────────

def bulk_delete(db: Session, note_ids: List[int]) -> int:
    """여러 메모 일괄 soft delete. 영향 받은 건수 반환."""
    now = datetime.utcnow()
    count = (
        db.query(Note)
        .filter(Note.id.in_(note_ids), Note.deleted_at.is_(None))
        .update({"deleted_at": now}, synchronize_session=False)
    )
    db.commit()
    return count


def bulk_archive(db: Session, note_ids: List[int]) -> int:
    """여러 메모 일괄 아카이브. 성공 건수 반환."""
    count = 0
    for note_id in note_ids:
        try:
            archive_note(db, note_id)
            count += 1
        except HTTPException:
            pass  # 존재하지 않는 메모는 스킵
    return count


def bulk_tag(
    db: Session,
    note_ids: List[int],
    add_tag_ids: List[int],
    remove_tag_ids: List[int],
) -> int:
    """여러 메모에 태그 일괄 추가/제거. 처리된 메모 건수 반환."""
    notes = db.query(Note).filter(
        Note.id.in_(note_ids), Note.deleted_at.is_(None)
    ).all()

    for note in notes:
        # 추가: 미존재 시에만 INSERT
        for tid in add_tag_ids:
            exists = db.query(NoteTag).filter(
                NoteTag.note_id == note.id,
                NoteTag.tag_id == tid,
                NoteTag.source == "note",
            ).first()
            if not exists:
                db.add(NoteTag(note_id=note.id, tag_id=tid, source="note"))

        # 제거: 존재하면 DELETE
        if remove_tag_ids:
            db.query(NoteTag).filter(
                NoteTag.note_id == note.id,
                NoteTag.tag_id.in_(remove_tag_ids),
                NoteTag.source == "note",
            ).delete(synchronize_session=False)

    db.commit()
    return len(notes)


def bulk_star(db: Session, note_ids: List[int], starred: bool) -> int:
    """여러 메모 별표 일괄 설정. 영향 받은 건수 반환."""
    count = (
        db.query(Note)
        .filter(Note.id.in_(note_ids), Note.deleted_at.is_(None))
        .update({"is_starred": 1 if starred else 0}, synchronize_session=False)
    )
    db.commit()
    return count


def search_titles(db: Session, q: str, limit: int = 10) -> List[dict]:
    """제목 부분 일치 검색 — 자동완성용 경량 API."""
    results = (
        db.query(Note.id, Note.title)
        .filter(Note.deleted_at.is_(None), Note.title.ilike(f"%{q}%"))
        .limit(limit)
        .all()
    )
    return [{"id": r.id, "title": r.title} for r in results]


def delete_tag(db: Session, tag_id: int) -> bool:
    tag = db.query(NoteTagDef).filter(NoteTagDef.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    db.delete(tag)  # CASCADE로 NoteTag 삭제됨
    db.commit()
    return True
