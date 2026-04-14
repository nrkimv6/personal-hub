"""Phase T4: E2E — rotation trigger + restore + content API

in-memory SQLite + 서비스 레이어 직접 호출 (실서버 불필요)
외부 side-effect(git rm/commit)는 mock.
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan_record import PlanRecord, PlanEvent
from app.modules.dev_runner.services.plan_record_service import (
    PlanRecordService,
    _compute_filename_hash,
)


def _make_tables(eng):
    PlanRecord.__table__.create(bind=eng, checkfirst=True)
    PlanEvent.__table__.create(bind=eng, checkfirst=True)


@pytest.fixture(scope="module")
def e2e_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _make_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def e2e_db(e2e_engine):
    Session = sessionmaker(bind=e2e_engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def e2e_svc(e2e_db):
    return PlanRecordService(e2e_db)


class TestRotationTriggerAndRestoreE2E:

    def test_e2e_rotation_trigger_and_restore(self, e2e_svc, e2e_db, tmp_path):
        """T4: 30건 archive fixture → 로테이션 대상 확인 → file_removed_at 마킹 → GET content → POST restore"""
        contents = {}
        records = []

        # 30건 archive 레코드 생성 (91일 전 archived, raw_content 있음)
        for i in range(30):
            fp = tmp_path / f"2026-01-{i+1:02d}-e2e-rotation.md"
            content = f"# E2E Rotation Test {i}\n\ncontent body {i}"
            fp.write_text(content, encoding="utf-8")

            record = e2e_svc.mark_archived(str(fp), str(fp), raw_content=content)
            record.archived_at = datetime.now() - timedelta(days=91)
            e2e_db.flush()

            records.append(record)
            contents[record.id] = (content, fp)

        e2e_db.commit()

        # 로테이션 대상 30건 확인
        targets = e2e_db.query(PlanRecord).filter(
            PlanRecord.file_removed_at.is_(None),
            PlanRecord.archived_at < datetime.now() - timedelta(days=90),
            PlanRecord.raw_content.isnot(None),
            PlanRecord.id.in_([r.id for r in records]),
        ).all()
        assert len(targets) == 30, f"로테이션 대상이 30건이어야 함. 실제: {len(targets)}"

        # 로테이션 시뮬레이션: file_removed_at 마킹
        now = datetime.now()
        for rec in records:
            rec.file_removed_at = now
        e2e_db.commit()

        # GET /records/{id}/content 역할: get_record() → raw_content 확인
        for rec in records:
            fetched = e2e_svc.get_record(rec.id)
            assert fetched is not None, f"record {rec.id} 조회 실패"
            assert fetched.raw_content == contents[rec.id][0], f"raw_content 불일치: record {rec.id}"
            assert fetched.file_removed_at is not None, "file_removed_at 마킹되어 있어야 함"

        # POST /records/{id}/restore 역할: restore_file() → 파일 복원 확인
        for rec in records:
            restored = e2e_svc.restore_file(rec.id)
            e2e_db.flush()

            assert restored is not None, f"restore_file({rec.id}) 반환값이 None"
            assert restored.file_removed_at is None, "복원 후 file_removed_at이 None이어야 함"

            fp = contents[rec.id][1]
            assert fp.exists(), f"복원 파일이 존재해야 함: {fp}"
            assert fp.read_text(encoding="utf-8") == contents[rec.id][0], f"복원 내용 불일치: {fp}"

        e2e_db.commit()
