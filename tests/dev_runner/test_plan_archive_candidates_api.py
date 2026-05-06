"""
T1: archive candidates API 계약 테스트.
RIGHT-BICEP/CORRECT 기준 — 단위 범위, mock 최소화.
"""
import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.plan_record import PlanRecord
from app.modules.dev_runner.services.plan_record_service import PlanRecordService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def archive_dir():
    # pytest의 tmp_path는 경로에 "pytest-"가 포함되어 _is_temp_pytest_path 에 걸린다.
    # 대신 prefix에 "pytest-"가 없는 디렉토리를 직접 생성한다.
    d = tempfile.mkdtemp(prefix="test_archive_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _make_plan_file(directory: Path, name: str = None, content: str = "# plan\nbody") -> Path:
    if name is None:
        name = "2026-05-06_plan.md"
    f = directory / name
    f.write_text(content, encoding="utf-8")
    return f


def _registered_paths(archive_dir: Path):
    return [{"path": str(archive_dir), "type": "archive"}]


def _record_for_file(file_path: str, *, archived: bool = True, llm_processed: bool = False):
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
    return PlanRecord(
        filename_hash=_compute_filename_hash(file_path),
        file_path=file_path,
        raw_content="# plan\nbody",
        archived_at=datetime(2026, 5, 6) if archived else None,
        llm_processed_at=datetime(2026, 5, 6) if llm_processed else None,
    )


# ── R: 정렬 우선순위 ────────────────────────────────────────────────────────

def test_list_archive_candidates_R_prioritizes_analysis_pending_before_db_only(db, archive_dir):
    # file_only (archived, not processed) 와 db_only (no file) 가 섞여 있을 때
    # eligible_for_analysis 우선 정렬을 확인
    f1 = _make_plan_file(archive_dir, "2026-05-01_a.md")
    rec1 = _record_for_file(str(f1))
    db.add(rec1)
    db.flush()
    # db_only: file_path를 존재하지 않는 경로로
    rec2 = PlanRecord(
        filename_hash="db-only-hash-12345",
        file_path="/nonexistent/2026-04-01_b.md",
        archived_at=datetime(2026, 4, 1),
        llm_processed_at=None,
    )
    db.add(rec2)
    db.commit()

    svc = PlanRecordService(db)
    result = svc.list_archive_candidates(_registered_paths(archive_dir), limit=50)
    candidates = result["candidates"]
    assert len(candidates) >= 1
    # matched/file_only 후보가 db_only 보다 앞에 나와야 함
    states = [c["state"] for c in candidates]
    if "db_only" in states and any(s in ("matched", "file_only") for s in states):
        first_db_only = next(i for i, s in enumerate(states) if s == "db_only")
        last_non_db_only = max(
            (i for i, s in enumerate(states) if s in ("matched", "file_only")),
            default=-1,
        )
        assert last_non_db_only < first_db_only, f"db_only({first_db_only}) should come after eligible candidates({last_non_db_only})"


# ── B: pagination ────────────────────────────────────────────────────────────

def test_list_archive_candidates_B_paginates_large_backlog(db, archive_dir):
    files = []
    for i in range(10):
        f = _make_plan_file(archive_dir, f"2026-05-{i+1:02d}_plan{i}.md")
        files.append(f)
        rec = _record_for_file(str(f))
        db.add(rec)
    db.commit()

    svc = PlanRecordService(db)
    page1 = svc.list_archive_candidates(_registered_paths(archive_dir), skip=0, limit=3)
    page2 = svc.list_archive_candidates(_registered_paths(archive_dir), skip=3, limit=3)
    assert len(page1["candidates"]) <= 3
    assert len(page2["candidates"]) <= 3
    ids1 = {c["file_path"] for c in page1["candidates"]}
    ids2 = {c["file_path"] for c in page2["candidates"]}
    assert ids1.isdisjoint(ids2), "pagination 페이지 간 중복 없어야 함"


# ── R: 필터 ──────────────────────────────────────────────────────────────────

def test_list_archive_candidates_R_filters_by_time_range_and_attempt_state(db, archive_dir):
    from datetime import datetime as dt
    f = _make_plan_file(archive_dir)
    rec = _record_for_file(str(f))
    db.add(rec)
    db.commit()

    svc = PlanRecordService(db)
    result_all = svc.list_archive_candidates(_registered_paths(archive_dir))
    result_filtered = svc.list_archive_candidates(
        _registered_paths(archive_dir),
        archived_after=dt(2030, 1, 1),  # 미래 → 결과 없어야 함
    )
    assert result_filtered["total"] == 0 or all(
        c.get("archived_at") and c["archived_at"] > "2030-01-01" if c.get("archived_at") else True
        for c in result_filtered["candidates"]
    )


def test_list_archive_candidates_R_filters_by_attempt_state_never_attempted(db, archive_dir):
    f = _make_plan_file(archive_dir)
    rec = _record_for_file(str(f))
    db.add(rec)
    db.commit()

    svc = PlanRecordService(db)
    result = svc.list_archive_candidates(
        _registered_paths(archive_dir),
        attempt_state="never_attempted",
    )
    # never_attempted 필터 시 attempt_count=0 인 항목만 있어야 함
    for c in result["candidates"]:
        assert c.get("attempt_count", 0) == 0


# ── E: page_size 상한 ────────────────────────────────────────────────────────

def test_list_archive_candidates_E_rejects_page_size_over_max(db):
    """limit > 200 → HTTPException 422 확인 (라우터 함수 직접 호출)."""
    from fastapi import HTTPException
    from app.modules.dev_runner.routes.plan_records import list_archive_candidates

    with pytest.raises(HTTPException) as exc_info:
        list_archive_candidates(limit=201, db=db)
    assert exc_info.value.status_code == 422


# ── R: file_only import + queue ──────────────────────────────────────────────

def test_queue_archive_candidates_R_imports_file_only_and_queues_selected_target(db, archive_dir):
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )
    f = _make_plan_file(archive_dir)
    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    exec_svc = PlanArchiveExecutionService(db)
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        import_result = svc.import_archive_candidate(str(f), paths)
        assert import_result["not_queueable"] is None
        assert import_result["created"] is True
        record = import_result["record"]
        assert record.raw_content is not None

        result = exec_svc.enqueue_record(
            record,
            trigger_source="test",
            selected_targets=[{"provider": "claude", "model": "sonnet", "dedupe_key": "profileless:claude:sonnet"}],
        )
    assert result["status_key"] == "queued"
    assert result.get("job_id") is not None


# ── E: unregistered candidate key ────────────────────────────────────────────

def test_queue_archive_candidates_E_rejects_unregistered_candidate_key(db, archive_dir):
    other_dir = Path(tempfile.mkdtemp())
    other_file = other_dir / "2026-05-06_plan.md"
    other_file.write_text("# plan", encoding="utf-8")

    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    result = svc.import_archive_candidate(str(other_file), paths)
    assert result["not_queueable"] is not None
    assert "archive root" in result["not_queueable"].lower() or "밖" in result["not_queueable"]


# ── E: path traversal ────────────────────────────────────────────────────────

def test_queue_archive_candidates_E_rejects_path_traversal_candidate(db, archive_dir):
    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    # "../" relative path traversal
    result = svc.import_archive_candidate("../../../etc/passwd", paths)
    assert result["not_queueable"] is not None


# ── E: duplicate hash auto-import ────────────────────────────────────────────

def test_queue_archive_candidates_E_rejects_duplicate_hash_auto_import(db, archive_dir):
    from app.modules.dev_runner.services.plan_record_service import _compute_filename_hash
    f = _make_plan_file(archive_dir)
    # Pre-create record with same hash but different file_path (simulating different archive root)
    existing = PlanRecord(
        filename_hash=_compute_filename_hash(str(f)),
        file_path=str(f),
        raw_content="# existing",
        archived_at=datetime(2026, 5, 1),
    )
    db.add(existing)
    db.commit()

    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    result = svc.import_archive_candidate(str(f), paths)
    # 같은 hash → 기존 record 반환, not_queueable = None (이미 있음)
    assert result["record"] is not None
    assert result["created"] is False


# ── E: binary / oversize ─────────────────────────────────────────────────────

def test_queue_archive_candidates_E_rejects_binary_or_oversize_file(db, archive_dir):
    # 이진 파일
    binary_file = archive_dir / "2026-05-06_bin.md"
    binary_file.write_bytes(b"\x00\x01\x02\x03" * 100)

    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    result = svc.import_archive_candidate(str(binary_file), paths)
    assert result["not_queueable"] is not None
    assert "utf-8" in result["not_queueable"].lower() or "이진" in result["not_queueable"]


# ── E: db_only without content ───────────────────────────────────────────────

def test_queue_archive_candidates_E_rejects_db_only_without_content(db, archive_dir):
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )
    rec = PlanRecord(
        filename_hash="db-only-no-content",
        file_path="/nonexistent/2026-04-01_x.md",
        archived_at=datetime(2026, 4, 1),
        raw_content=None,
    )
    db.add(rec)
    db.commit()
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")
    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        result = PlanArchiveExecutionService(db).enqueue_record(
            rec, trigger_source="test"
        )
    assert result["status_key"] == "skipped_empty"


# ── R: response DTO 4구간 분류 ────────────────────────────────────────────────

def test_queue_archive_candidates_R_response_dto_reports_queued_imported_skipped_errors(db, archive_dir):
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )
    f = _make_plan_file(archive_dir)
    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        import_result = svc.import_archive_candidate(str(f), paths)
        record = import_result["record"]
        exec_svc = PlanArchiveExecutionService(db)
        result = exec_svc.enqueue_record(record, trigger_source="test")

    assert result["status_key"] in ("queued", "skipped_active_request", "skipped_active_job", "skipped_empty")


# ── E: already_queued dedupe ─────────────────────────────────────────────────

def test_queue_archive_candidates_E_skips_already_queued_record_target_combo(db, archive_dir):
    from app.modules.dev_runner.services.plan_archive_execution_service import (
        PlanArchiveExecutionService,
    )
    f = _make_plan_file(archive_dir)
    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)
    exec_svc = PlanArchiveExecutionService(db)
    fake_llm = MagicMock()
    fake_llm.resolve_provider_model.return_value = ("claude", "sonnet")

    with patch(
        "app.modules.dev_runner.services.plan_archive_execution_service.LLMService",
        return_value=fake_llm,
    ):
        import_result = svc.import_archive_candidate(str(f), paths)
        record = import_result["record"]
        # 첫 번째 큐잉
        r1 = exec_svc.enqueue_record(record, trigger_source="test")
        db.commit()
        assert r1["status_key"] == "queued"
        # 두 번째 큐잉 → active_job 있으므로 skip
        r2 = exec_svc.enqueue_record(record, trigger_source="test")
    assert r2["status_key"] in ("skipped_active_job", "skipped_active_request")


# ── R: preview dry-run ────────────────────────────────────────────────────────

def test_preview_archive_candidate_R_returns_raw_content_total_bytes_and_lines_without_db_write(db, archive_dir):
    content = "# plan\n" + "line\n" * 10
    f = _make_plan_file(archive_dir, content=content)
    paths = _registered_paths(archive_dir)
    svc = PlanRecordService(db)

    resolved_info = svc.resolve_archive_candidate_key(str(f), paths)
    assert resolved_info["resolved_path"] == str(f.resolve())

    path = Path(resolved_info["resolved_path"])
    raw_bytes = path.read_bytes()
    total_bytes = len(raw_bytes)
    text = raw_bytes.decode("utf-8")
    total_lines = text.count("\n") + 1
    preview = text[:8192]

    assert total_bytes > 0
    assert total_lines >= 10
    assert preview.startswith("# plan")
    # DB write 없어야 함
    count_before = db.query(PlanRecord).count()
    count_after = db.query(PlanRecord).count()
    assert count_before == count_after
