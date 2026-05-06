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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import TaskSchedule, TaskScheduleRun
from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.claude_worker.models.llm_request import LLMRequest
from app.modules.dev_runner.services.plan_archive_retrieval_readiness import (
    get_plan_archive_retrieval_readiness,
)

logger = logging.getLogger(__name__)
ARCHIVE_FILE_RETENTION_DAYS = 7

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


def _is_temp_pytest_path(file_path: str) -> bool:
    """Return True for pytest-created temp plan/archive paths."""
    normalized = str(file_path or "").replace("\\", "/").lower()
    return (
        "/tmp/pytest-" in normalized
        or "/tmp/pytest-of-" in normalized
        or "/temp/pytest-" in normalized
        or "/temp/pytest-of-" in normalized
    )


def _exclude_temp_pytest_records(query):
    """Apply the same pytest temp path exclusion to SQLAlchemy queries."""
    return query.filter(
        ~or_(
            PlanRecord.file_path.ilike(r"%\Temp\pytest-%"),
            PlanRecord.file_path.ilike(r"%\Temp\pytest-of-%"),
            PlanRecord.file_path.ilike("%/tmp/pytest-%"),
            PlanRecord.file_path.ilike("%/tmp/pytest-of-%"),
        )
    )


def _add_event(db: Session, record: PlanRecord, event_type: str, detail: Optional[dict] = None):
    """이벤트 추가 헬퍼"""
    event = PlanEvent(
        plan_record_id=record.id,
        event_type=event_type,
        detail=detail,
    )
    db.add(event)


def _schedule_file_delete_after(record: PlanRecord, base_time: Optional[datetime] = None) -> None:
    """Set file_delete_after when DB raw_content is available after LLM processing."""
    if record.raw_content and record.llm_processed_at:
        anchor = base_time or record.llm_processed_at
        record.file_delete_after = anchor + timedelta(days=ARCHIVE_FILE_RETENTION_DAYS)


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
            status="planned",
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

    def mark_archived(self, file_path: str, new_path: str, raw_content: Optional[str] = None) -> Optional[PlanRecord]:
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
        if raw_content:
            record.raw_content = raw_content
            record.file_removed_at = None
            _schedule_file_delete_after(record, datetime.now())
        _add_event(self.db, record, "archived", {"archive_path": new_path})
        return record

    def update_status(self, file_path: str, new_status: str) -> Optional[PlanRecord]:
        """상태 전이: file_path로 레코드 조회 → status 변경 + status_changed 이벤트 기록"""
        filename_hash = _compute_filename_hash(file_path)
        record = self.db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if not record:
            return None
        old_status = record.status
        if old_status == new_status:
            return record
        record.status = new_status
        record.updated_at = datetime.now()
        _add_event(self.db, record, "status_changed", {"from": old_status, "to": new_status})
        return record

    def sync_from_workflow(self, workflow) -> Optional[PlanRecord]:
        """workflow 상태를 plan_record 상태로 동기화

        workflow status 매핑:
          planned    → planned
          running    → in_progress
          completed  → completed
          failed     → planned  (재시도 가능)
        """
        STATUS_MAP = {
            "planned": "planned",
            "running": "in_progress",
            "completed": "completed",
            "failed": "planned",
        }
        file_path = getattr(workflow, "plan_path", None) or getattr(workflow, "file_path", None)
        if not file_path:
            return None
        workflow_status = getattr(workflow, "status", None)
        if not workflow_status:
            return None
        new_status = STATUS_MAP.get(workflow_status)
        if not new_status:
            return None
        return self.update_status(file_path, new_status)

    def get_record(self, record_id: int) -> Optional[PlanRecord]:
        """개별 레코드 조회 (events 포함)"""
        return self.db.query(PlanRecord).filter_by(id=record_id).first()

    def restore_file(self, record_id: int) -> Optional[PlanRecord]:
        """raw_content → 파일 복원, file_removed_at 초기화, restored 이벤트 기록"""
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if not record:
            return None
        if not record.raw_content:
            return None
        restore_path = Path(record.file_path)
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        restore_path.write_text(record.raw_content, encoding="utf-8")
        record.file_removed_at = None
        _schedule_file_delete_after(record, datetime.now())
        record.updated_at = datetime.now()
        _add_event(self.db, record, "restored", {"path": str(restore_path)})
        return record

    def ingest_single(
        self,
        file_path: str,
        project: Optional[str] = None,
        raw_content: Optional[str] = None,
        title: Optional[str] = None,
        status: Optional[str] = None,
    ) -> PlanRecord:
        """단건 archive ingest (wtools HTTP 호출용): upsert + raw_content 저장"""
        filename_hash = _compute_filename_hash(file_path)
        record = self.db.query(PlanRecord).filter_by(filename_hash=filename_hash).first()
        if record:
            # update
            now = datetime.now()
            old_path = record.file_path
            path_changed = old_path != file_path
            if path_changed:
                record.file_path = file_path
                _add_event(
                    self.db,
                    record,
                    "path_changed",
                    {"from": old_path, "to": file_path, "source": "ingest_single"},
                )
            record.file_removed_at = None
            if record.archived_at is None:
                record.archived_at = now
            if project:
                record.project = project
            if raw_content:
                record.raw_content = raw_content
                _schedule_file_delete_after(record, now)
            if title:
                record.title = title
            if status:
                record.status = status
            record.updated_at = now
            _add_event(
                self.db,
                record,
                "ingested",
                {
                    "source": "ingest_single",
                    "updated": True,
                    "old_path": old_path if path_changed else None,
                    "new_path": file_path,
                },
            )
        else:
            # create
            if title is None:
                title = self._extract_title_from_md(file_path) if Path(file_path).exists() else None
            if project is None:
                project = self._detect_project_from_path(file_path)
            record = PlanRecord(
                filename_hash=filename_hash,
                file_path=file_path,
                title=title,
                project=project,
                status=status or "archived",
                archived_at=datetime.now(),
                raw_content=raw_content,
            )
            _schedule_file_delete_after(record)
            self.db.add(record)
            self.db.flush()
            _add_event(self.db, record, "ingested", {"source": "ingest_single", "created": True})
        return record

    def update_claude_session_id(self, record_id: int, session_id: str) -> None:
        """plan_records에 claude_session_id 저장 (dev-runner executor 발급 UUID)."""
        record = self.db.query(PlanRecord).filter_by(id=record_id).first()
        if record:
            record.claude_session_id = session_id
            self.db.commit()

    def list_records(
        self,
        project: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        q: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 50,
        deep: bool = False,
        exclude_temp: bool = True,
    ) -> List[PlanRecord]:
        """레코드 목록 조회 (페이지네이션 + 필터 + keyword/date_range 검색)

        deep=True 시 raw_content까지 full-text 검색 (summary/title + raw_content OR)
        """
        from sqlalchemy import or_
        query = self.db.query(PlanRecord)
        if exclude_temp:
            query = _exclude_temp_pytest_records(query)
        if project:
            query = query.filter(PlanRecord.project == project)
        if status:
            if status == 'archived':
                query = query.filter(PlanRecord.archived_at.isnot(None))
            else:
                query = query.filter(PlanRecord.status == status)
        if category:
            query = query.filter(PlanRecord.category == category)
        if tags:
            for tag in tags:
                query = query.filter(PlanRecord.tags.contains(tag))
        if q:
            conditions = [
                PlanRecord.summary.ilike(f"%{q}%"),
                PlanRecord.title.ilike(f"%{q}%"),
            ]
            if deep:
                conditions.append(PlanRecord.raw_content.ilike(f"%{q}%"))
            query = query.filter(or_(*conditions))
        if date_from:
            query = query.filter(PlanRecord.archived_at >= date_from)
        if date_to:
            query = query.filter(PlanRecord.archived_at <= date_to)
        query = query.order_by(PlanRecord.updated_at.desc())
        records = query.offset(skip).limit(limit).all()
        try:
            from app.modules.dev_runner.services.plan_archive_execution_service import (
                PlanArchiveExecutionService,
            )

            PlanArchiveExecutionService(self.db).attach_latest_summaries(records)
        except Exception as exc:
            logger.warning("[plan-archive] execution summary attach failed: %s", exc)
        return records

    def get_plan_archive_health(self, include_temp: bool = False) -> dict:
        """Return scheduler-facing Plan Archive health without exposing DB details."""
        archived_query = self.db.query(PlanRecord).filter(PlanRecord.archived_at.isnot(None))
        all_archived = archived_query.count()
        llm_processed = archived_query.filter(PlanRecord.llm_processed_at.isnot(None)).count()
        llm_unprocessed = archived_query.filter(PlanRecord.llm_processed_at.is_(None)).count()

        temp_archived_query = archived_query.filter(
            or_(
                PlanRecord.file_path.ilike(r"%\Temp\pytest-%"),
                PlanRecord.file_path.ilike(r"%\Temp\pytest-of-%"),
                PlanRecord.file_path.ilike("%/tmp/pytest-%"),
                PlanRecord.file_path.ilike("%/tmp/pytest-of-%"),
            )
        )
        temp_pytest_total = temp_archived_query.count()
        temp_pytest_unprocessed = temp_archived_query.filter(
            PlanRecord.llm_processed_at.is_(None)
        ).count()

        real_unprocessed_query = archived_query.filter(PlanRecord.llm_processed_at.is_(None))
        if not include_temp:
            real_unprocessed_query = _exclude_temp_pytest_records(real_unprocessed_query)
        real_unprocessed = real_unprocessed_query.count()
        oldest_unprocessed_at = real_unprocessed_query.with_entities(
            func.min(PlanRecord.archived_at)
        ).scalar()

        request_query = self.db.query(LLMRequest).filter(
            LLMRequest.caller_type == "plan_archive_analyze",
            LLMRequest.deleted_at.is_(None),
        )
        # /automation archive health와 /llm queue는 모두 llm_requests 상태를 원천으로 본다.
        pending_or_processing_requests = request_query.filter(
            LLMRequest.status.in_(["pending", "processing"])
        ).count()
        failed_requests = request_query.filter(LLMRequest.status == "failed").count()
        latest_failed = (
            request_query.filter(LLMRequest.status == "failed")
            .order_by(LLMRequest.requested_at.desc())
            .first()
        )
        now = datetime.now()
        retention_base = archived_query.filter(
            PlanRecord.llm_processed_at.isnot(None),
            PlanRecord.raw_content.isnot(None),
        )
        file_retention_due = retention_base.filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.file_delete_after.isnot(None),
            PlanRecord.file_delete_after <= now,
        ).count()
        file_retention_scheduled = retention_base.filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.file_delete_after.isnot(None),
            PlanRecord.file_delete_after > now,
        ).count()
        file_removed = archived_query.filter(PlanRecord.file_removed_at.isnot(None)).count()
        oldest_file_delete_after = retention_base.filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.file_delete_after.isnot(None),
        ).with_entities(func.min(PlanRecord.file_delete_after)).scalar()

        schedule = (
            self.db.query(TaskSchedule)
            .filter(TaskSchedule.target_type == TaskSchedule.TARGET_TYPE_PLAN_ARCHIVE_ANALYZE)
            .order_by(TaskSchedule.id.asc())
            .first()
        )
        latest_completed = None
        latest_failed_run = None
        if schedule:
            latest_completed = (
                self.db.query(TaskScheduleRun)
                .filter(
                    TaskScheduleRun.schedule_id == schedule.id,
                    TaskScheduleRun.status == TaskScheduleRun.STATUS_COMPLETED,
                )
                .order_by(TaskScheduleRun.finished_at.desc())
                .first()
            )
            latest_failed_run = (
                self.db.query(TaskScheduleRun)
                .filter(
                    TaskScheduleRun.schedule_id == schedule.id,
                    TaskScheduleRun.status == TaskScheduleRun.STATUS_FAILED,
                )
                .order_by(TaskScheduleRun.finished_at.desc())
                .first()
            )

        return {
            "archived_total": all_archived,
            "llm_processed": llm_processed,
            "llm_unprocessed": llm_unprocessed,
            "real_unprocessed": real_unprocessed,
            "temp_pytest_total": temp_pytest_total,
            "temp_pytest_unprocessed": temp_pytest_unprocessed,
            "pending_or_processing_requests": pending_or_processing_requests,
            "failed_requests": failed_requests,
            "file_retention_due": file_retention_due,
            "file_retention_scheduled": file_retention_scheduled,
            "file_removed": file_removed,
            "oldest_file_delete_after": oldest_file_delete_after.isoformat() if oldest_file_delete_after else None,
            "latest_failed_request": {
                "id": latest_failed.id,
                "caller_id": latest_failed.caller_id,
                "requested_at": latest_failed.requested_at.isoformat() if latest_failed.requested_at else None,
                "error_message": latest_failed.error_message,
            } if latest_failed else None,
            "oldest_unprocessed_at": oldest_unprocessed_at.isoformat() if oldest_unprocessed_at else None,
            "plan_archive_schedule": {
                "id": schedule.id,
                "enabled": schedule.enabled,
                "schedule_value": schedule.schedule_value,
                "last_run": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                "last_success": latest_completed.finished_at.isoformat()
                if latest_completed and latest_completed.finished_at
                else None,
                "last_failure": latest_failed_run.finished_at.isoformat()
                if latest_failed_run and latest_failed_run.finished_at
                else None,
            } if schedule else None,
            "retrieval_db_readiness": get_plan_archive_retrieval_readiness(self.db),
        }

    def get_guide_status(self, include_history: bool = False) -> List[dict]:
        """가이드별 staleness 정보 반환.

        _meta.yaml에서 가이드 목록 + owns_archive_tags 로드 →
        PlanRecord archived_at IS NOT NULL 전체 조회 →
        파일명에서 extract_wiki_tags()로 태그 추출 →
        last_archive_scan 이후 archived_at인 것 → pending_count.

        include_history=True: PlanEvent(event_type="devguide_staleness") 최근 10건 포함.

        Returns:
            [{guide, last_updated, pending_count, pending_archives: [{file_path, summary, archived_at}]}]
        """
        try:
            from app.shared.wiki_tags import extract_wiki_tags, load_whitelist, load_meta_yaml
        except ImportError:
            logger.warning("wiki_tags not available — returning empty guide status")
            return []

        meta = load_meta_yaml()
        try:
            whitelist = load_whitelist()
        except Exception as e:
            logger.warning(f"whitelist load failed: {e}")
            whitelist = set()

        records_query = self.db.query(PlanRecord).filter(PlanRecord.archived_at.isnot(None))
        records = _exclude_temp_pytest_records(records_query).all()

        result: List[dict] = []
        for guide_name, guide_meta in meta.items():
            owns = set(guide_meta.get("owns_archive_tags") or [])
            last_scan_str = guide_meta.get("last_archive_scan") or ""
            try:
                last_scan = datetime.strptime(last_scan_str, "%Y-%m-%d") if last_scan_str else None
            except ValueError:
                last_scan = None

            pending_archives: List[dict] = []
            for rec in records:
                if not owns:
                    continue
                filename = Path(rec.file_path).name
                tags = set(extract_wiki_tags(filename, whitelist))
                if not (tags & owns):
                    continue
                # last_archive_scan 이후 archived_at인 것만 pending
                if last_scan and rec.archived_at and rec.archived_at <= last_scan:
                    continue
                pending_archives.append({
                    "file_path": rec.file_path,
                    "summary": rec.summary,
                    "archived_at": rec.archived_at.isoformat() if rec.archived_at else None,
                })

            item: dict = {
                "guide": guide_name,
                "last_updated": last_scan_str,
                "pending_count": len(pending_archives),
                "pending_archives": pending_archives,
            }

            if include_history:
                history = (
                    self.db.query(PlanEvent)
                    .filter(PlanEvent.event_type == "devguide_staleness")
                    .order_by(PlanEvent.created_at.desc())
                    .limit(10)
                    .all()
                )
                item["staleness_history"] = [
                    {
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                        "pending_count": (e.detail or {}).get("pending_count"),
                    }
                    for e in history
                ]

            result.append(item)

        return result

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
        q = _exclude_temp_pytest_records(q)
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

    def get_active_claim(self, file_path: str) -> Optional[dict]:
        """plan path로 PlanRecord를 확보한 뒤 active claim 요약을 반환한다.

        claim이 없거나 PlanExecutionClaim 테이블이 아직 없으면 None을 반환한다.
        """
        try:
            from app.models.plan_execution_claim import PlanExecutionClaim
            from app.modules.dev_runner.services.plan_execution_claim_service import (
                get_active_claim_for_plan,
            )
            claim = get_active_claim_for_plan(self.db, file_path)
            if not claim:
                return None
            return {
                "claim_id": claim.claim_id,
                "state": claim.state,
                "engine": claim.engine,
                "runner_id": claim.runner_id,
                "session_id": claim.session_id,
                "heartbeat_at": claim.heartbeat_at.isoformat() if claim.heartbeat_at else None,
                "lease_expires_at": claim.lease_expires_at.isoformat() if claim.lease_expires_at else None,
            }
        except Exception as e:
            logger.debug("get_active_claim failed for %s: %s", file_path, e)
            return None
