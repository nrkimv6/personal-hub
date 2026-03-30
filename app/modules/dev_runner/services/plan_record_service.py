"""
PlanRecordService — 계획서 메타데이터 DB 관리

파일 기반 plan_service와 병행 동작:
- 파일 파싱(상태/진행률)은 plan_service가 담당
- 메모/이력 DB 관리는 이 서비스가 담당
"""
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from sqlalchemy.orm import Session

from app.models.plan_record import PlanRecord, PlanEvent

logger = logging.getLogger(__name__)

# plan 파일 패턴 필터 — YYYY-MM-DD 로 시작하는 .md 파일만 허용
PLAN_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[_-].*\.md$")

# 등록 제외 파일 목록 — 문서/설정 파일
EXCLUDE_FILES = {
    "CLAUDE.md", "CHANGELOG.md", "README.md", "TODO.md",
    "MANUAL_TASKS.md", "DONE.md", "REQUIREMENTS.md",
}


def _is_plan_file(file_path) -> bool:
    """파일이 plan 파일 기준에 맞는지 확인 (PLAN_FILE_PATTERN + EXCLUDE_FILES)"""
    name = Path(file_path).name
    return name not in EXCLUDE_FILES and bool(PLAN_FILE_PATTERN.match(name))


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

        # title/project 미제공 시 파일에서 자동 추출
        if title is None:
            title = self._extract_title_from_md(file_path)
        if project is None:
            project = self._detect_project_from_path(file_path)

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
        record.status = 'archived'
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
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[PlanRecord]:
        """레코드 목록 조회 (페이지네이션 + 필터)"""
        q = self.db.query(PlanRecord)
        if project:
            q = q.filter(PlanRecord.project == project)
        if status:
            if status == 'archived':
                q = q.filter(PlanRecord.archived_at.isnot(None))
            else:
                q = q.filter(PlanRecord.status == status)
        if category:
            q = q.filter(PlanRecord.category == category)
        if tags:
            from sqlalchemy import func
            for tag in tags:
                q = q.filter(PlanRecord.tags.contains(tag))
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
        """이벤트 목록 조회 (타임라인 뷰용)

        pytest 통합테스트 실행 시 생성되는 임시 경로 레코드를 제외한다.
        제외 패턴: \\Temp\\pytest- (Windows) 또는 /tmp/pytest- (Linux/Mac)
        """
        q = self.db.query(PlanEvent).join(PlanRecord, PlanEvent.plan_record_id == PlanRecord.id)
        # pytest 임시 경로 필터 (대소문자 무시)
        q = q.filter(
            ~PlanRecord.file_path.ilike(r"%\Temp\pytest-%"),
            ~PlanRecord.file_path.ilike("%/tmp/pytest-%"),
        )
        if event_type:
            q = q.filter(PlanEvent.event_type == event_type)
        if date_from:
            q = q.filter(PlanEvent.created_at >= date_from)
        if date_to:
            q = q.filter(PlanEvent.created_at <= date_to)
        q = q.order_by(PlanEvent.created_at.desc())
        return q.offset(skip).limit(limit).all()

    @staticmethod
    def _extract_title_from_md(file_path: str) -> Optional[str]:
        """파일 첫 줄 `# ` 파싱하여 title 반환"""
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                first_line = f.readline().strip()
            if first_line.startswith("# "):
                return first_line[2:].strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _detect_project_from_path(file_path: str) -> Optional[str]:
        """경로에서 프로젝트명 추출 (docs/archive/{project}/... 패턴)"""
        parts = Path(file_path).parts
        for i, part in enumerate(parts):
            if part == "archive" and i + 1 < len(parts):
                return parts[i + 1]
        return None

    def bulk_import_archived(self, archive_dir: str) -> dict:
        """archived plan 파일 일괄 DB 이관

        archive_dir 하위 모든 .md 파일을 스캔하여 plan_records에 등록.
        이미 존재하는 레코드는 category만 UPDATE.

        Returns:
            {"created": int, "updated": int, "skipped": int, "errors": list}
        """
        created = updated = skipped = 0
        errors: List[str] = []

        archive_path = Path(archive_dir)
        if not archive_path.exists():
            return {"created": 0, "updated": 0, "skipped": 0, "errors": [f"archive_dir not found: {archive_dir}"]}

        md_files = list(archive_path.rglob("*.md"))

        for f in md_files:
            try:
                if not _is_plan_file(f):
                    skipped += 1
                    continue
                file_str = str(f)
                filename_hash = _compute_filename_hash(file_str)
                category = self._detect_project_from_path(file_str)
                title = self._extract_title_from_md(file_str)

                existing = self.db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
                if existing:
                    if existing.category != category:
                        existing.category = category
                        existing.updated_at = datetime.now()
                        updated += 1
                    else:
                        skipped += 1
                else:
                    project = self._detect_project_from_path(file_str)
                    record = PlanRecord(
                        filename_hash=filename_hash,
                        file_path=file_str,
                        title=title,
                        project=project,
                        category=category,
                        archived_at=datetime.now(),
                        status="archived",
                    )
                    self.db.add(record)
                    self.db.flush()
                    _add_event(self.db, record, "created", {"file_path": file_str, "source": "bulk_import"})
                    created += 1
            except Exception as e:
                errors.append(f"{f}: {e}")
                logger.warning(f"bulk_import_archived error for {f}: {e}")

        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            errors.append(f"commit error: {e}")

        return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}

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
            if folder.is_dir():
                if entry.get("type") == "archive":
                    files = list(folder.rglob("*.md"))
                else:
                    files = list(folder.glob("*.md"))
            else:
                files = [folder]
            for f in files:
                if not f.is_file():
                    continue
                if not _is_plan_file(f):
                    continue
                h = _compute_filename_hash(str(f))
                seen_hashes.add(h)
                if h not in all_records:
                    # 신규
                    record = self.get_or_create(str(f))
                    created += 1
                else:
                    record = all_records[h]
                    # title/project 백필 (기존 레코드에 없으면 갱신)
                    updated_fields = False
                    if record.title is None:
                        extracted_title = self._extract_title_from_md(str(f))
                        if extracted_title:
                            record.title = extracted_title
                            updated_fields = True
                    if record.project is None:
                        detected_project = self._detect_project_from_path(str(f))
                        if detected_project:
                            record.project = detected_project
                            updated_fields = True
                    if updated_fields:
                        record.updated_at = datetime.now()
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
