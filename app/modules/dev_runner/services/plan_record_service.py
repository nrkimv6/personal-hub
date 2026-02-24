"""
PlanRecordService — 계획서 메타데이터 DB 관리

파일 기반 plan_service와 병행 동작:
- 파일 파싱(상태/진행률)은 plan_service가 담당
- 메모/이력 DB 관리는 이 서비스가 담당
"""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanEvent

logger = logging.getLogger(__name__)


def _compute_filename_hash(file_path: str) -> str:
    """파일명 기반 sha256 해시 생성 (안정 식별자)

    생성 시각 대신 파일명(날짜 포함)만으로 해시를 만들어
    같은 파일에 대해 항상 동일한 해시를 반환한다.
    """
    filename = Path(file_path).name
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def _add_event(db: Session, record: PlanRecord, event_type: str, detail: Optional[dict] = None):
    """이벤트 추가 헬퍼"""
    event = PlanEvent(
        plan_record_id=record.id,
        event_type=event_type,
        detail=detail,
    )
    db.add(event)


class PlanRecordService:
    """계획서 레코드 DB CRUD + 동기화 로직"""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, file_path: str, title: Optional[str] = None, project: Optional[str] = None) -> PlanRecord:
        """filename_hash로 레코드 조회, 없으면 생성 + created 이벤트"""
        filename_hash = _compute_filename_hash(file_path)
        record = self.db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if record:
            # file_path 캐시 갱신 (이동 감지)
            if record.file_path != file_path:
                old_path = record.file_path
                record.file_path = file_path
                record.updated_at = datetime.now()
                _add_event(self.db, record, "path_changed", {"from": old_path, "to": file_path})
            return record

        record = PlanRecord(
            filename_hash=filename_hash,
            file_path=file_path,
            title=title,
            project=project,
        )
        self.db.add(record)
        self.db.flush()  # id 생성
        _add_event(self.db, record, "created", {"file_path": file_path})
        return record

    def update_memo_draft(self, record_id: int, draft: str) -> Optional[PlanRecord]:
        """자동저장: memo_draft 갱신 (확정 memo는 변경하지 않음)"""
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if not record:
            return None
        record.memo_draft = draft
        record.updated_at = datetime.now()
        return record

    def confirm_memo(self, record_id: int) -> Optional[PlanRecord]:
        """수동저장: memo_draft → memo 확정, memo_draft 초기화, memo_updated 이벤트"""
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if not record:
            return None
        old_memo = record.memo or ""
        record.memo = record.memo_draft or old_memo
        record.memo_draft = None
        record.updated_at = datetime.now()
        _add_event(self.db, record, "memo_updated", {"preview": (record.memo or "")[:100]})
        return record

    def rollback_memo(self, record_id: int) -> Optional[PlanRecord]:
        """롤백: memo_draft를 마지막 확정 memo로 되돌림"""
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if not record:
            return None
        record.memo_draft = record.memo or ""
        record.updated_at = datetime.now()
        return record

    def mark_archived(self, file_path: str, new_path: str) -> Optional[PlanRecord]:
        """archive 완료 기록: archived_at 기록, file_path 갱신, archived 이벤트"""
        filename_hash = _compute_filename_hash(file_path)
        record = self.db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if not record:
            # archive 전에 레코드가 없으면 생성
            record = PlanRecord(
                filename_hash=filename_hash,
                file_path=new_path,
            )
            self.db.add(record)
            self.db.flush()

        record.file_path = new_path
        record.archived_at = datetime.now()
        record.updated_at = datetime.now()
        _add_event(self.db, record, "archived", {"archive_path": new_path})
        return record

    def get_record(self, record_id: int) -> Optional[PlanRecord]:
        """개별 레코드 조회 (events 포함)"""
        return self.db.query(PlanRecord).filter_by(id=record_id).first()

    def list_records(
        self,
        project: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[PlanRecord]:
        """레코드 목록 조회 (페이지네이션 + 필터)"""
        q = self.db.query(PlanRecord)
        if project:
            q = q.filter(PlanRecord.project == project)
        if status:
            q = q.filter(PlanRecord.status == status)
        q = q.order_by(PlanRecord.updated_at.desc())
        return q.offset(skip).limit(limit).all()

    def list_events(
        self,
        event_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[PlanEvent]:
        """이벤트 목록 조회 (타임라인 뷰용)"""
        q = self.db.query(PlanEvent)
        if event_type:
            q = q.filter(PlanEvent.event_type == event_type)
        if date_from:
            q = q.filter(PlanEvent.created_at >= date_from)
        if date_to:
            q = q.filter(PlanEvent.created_at <= date_to)
        q = q.order_by(PlanEvent.created_at.desc())
        return q.offset(skip).limit(limit).all()

    def sync_all(self, registered_paths: List[dict]) -> dict:
        """수동 동기화: 등록된 폴더 전체 스캔 → 신규/이동/missing 감지

        Args:
            registered_paths: [{"path": str, "type": str}, ...]

        Returns:
            {"created": int, "updated": int, "missing": int}
        """
        created = updated = missing = 0

        # DB에 있는 모든 레코드의 hash → record 매핑
        all_records: Dict[str, PlanRecord] = {
            r.filename_hash: r
            for r in self.db.query(PlanRecord).all()
        }
        seen_hashes = set()

        for entry in registered_paths:
            folder = Path(entry["path"])
            if not folder.exists():
                continue
            files = list(folder.glob("*.md")) if folder.is_dir() else [folder]
            for f in files:
                if not f.is_file():
                    continue
                h = _compute_filename_hash(str(f))
                seen_hashes.add(h)
                if h not in all_records:
                    # 신규
                    record = self.get_or_create(str(f))
                    created += 1
                else:
                    record = all_records[h]
                    if record.file_path != str(f):
                        # 경로 변경
                        old = record.file_path
                        record.file_path = str(f)
                        record.updated_at = datetime.now()
                        _add_event(self.db, record, "path_changed", {"from": old, "to": str(f)})
                        updated += 1

        # DB에 있지만 스캔에서 발견 안 된 것 → missing
        for h, record in all_records.items():
            if h not in seen_hashes and record.archived_at is None:
                _add_event(self.db, record, "missing", {"file_path": record.file_path})
                missing += 1

        self.db.commit()
        return {"created": created, "updated": updated, "missing": missing}
