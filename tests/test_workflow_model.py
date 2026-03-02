"""
Workflow SQLAlchemy 모델 단위 테스트

Phase T1 TC:
  - test_workflow_model_create: R(Right) — 생성, 상태 상수, 기본값
  - test_workflow_model_mark_running: R(Right) — mark_running 헬퍼
  - test_workflow_model_mark_merged: R(Right) — mark_merged 헬퍼
  - test_workflow_model_mark_failed: R(Right) — mark_failed 헬퍼
  - test_workflow_model_boundary_null_plan: B(Boundary) — plan_file=None
  - test_workflow_model_boundary_duplicate_slug: B(Boundary) — slug 중복
"""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models.base import Base
from app.models.workflow import (
    Workflow,
    STATUS_PLANNED, STATUS_RUNNING, STATUS_MERGE_PENDING,
    STATUS_MERGING, STATUS_MERGED, STATUS_FAILED, STATUS_CANCELLED,
)


@pytest.fixture
def session():
    """인메모리 SQLite + Workflow 테이블만 생성"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Workflow 테이블만 개별 생성 (다른 모델 FK 참조 오류 방지)
    Workflow.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_workflow_model_create(session):
    """R(Right): Workflow 모델 인스턴스 생성 → 상태 상수, 기본값 확인"""
    # 상태 상수 확인
    assert STATUS_PLANNED == "planned"
    assert STATUS_RUNNING == "running"
    assert STATUS_MERGE_PENDING == "merge_pending"
    assert STATUS_MERGING == "merging"
    assert STATUS_MERGED == "merged"
    assert STATUS_FAILED == "failed"
    assert STATUS_CANCELLED == "cancelled"

    # 레코드 생성
    wf = Workflow(slug="test-slug", plan_file="docs/plan/test.md", status=STATUS_PLANNED, created_at=datetime.now())
    session.add(wf)
    session.commit()
    session.refresh(wf)

    assert wf.id is not None
    assert wf.slug == "test-slug"
    assert wf.status == STATUS_PLANNED
    assert wf.plan_file == "docs/plan/test.md"
    assert wf.runner_id is None
    assert wf.error_message is None


def test_workflow_model_mark_running(session):
    """R(Right): mark_running(runner_id, branch, worktree_path) → status/started_at/runner_id/branch/worktree_path 설정"""
    wf = Workflow(slug="test-running", status=STATUS_PLANNED, created_at=datetime.now())
    session.add(wf)
    session.commit()

    before = datetime.now()
    wf.mark_running("runner-abc", "plan/test-slug", "/path/to/worktree")
    session.commit()

    assert wf.status == STATUS_RUNNING
    assert wf.runner_id == "runner-abc"
    assert wf.branch == "plan/test-slug"
    assert wf.worktree_path == "/path/to/worktree"
    assert wf.started_at is not None
    assert wf.started_at >= before


def test_workflow_model_mark_merged(session):
    """R(Right): mark_merged(commit_hash) → status/commit_hash/merged_at/finished_at 설정"""
    wf = Workflow(slug="test-merged", status=STATUS_MERGING, created_at=datetime.now())
    session.add(wf)
    session.commit()

    before = datetime.now()
    wf.mark_merged("abc123def456")
    session.commit()

    assert wf.status == STATUS_MERGED
    assert wf.commit_hash == "abc123def456"
    assert wf.merged_at is not None
    assert wf.finished_at is not None
    assert wf.merged_at >= before


def test_workflow_model_mark_failed(session):
    """R(Right): mark_failed(error_message) → status/error_message/finished_at 설정"""
    wf = Workflow(slug="test-failed", status=STATUS_RUNNING, created_at=datetime.now())
    session.add(wf)
    session.commit()

    before = datetime.now()
    wf.mark_failed("Process exited with code 1")
    session.commit()

    assert wf.status == STATUS_FAILED
    assert wf.error_message == "Process exited with code 1"
    assert wf.finished_at is not None
    assert wf.finished_at >= before


def test_workflow_model_boundary_null_plan(session):
    """B(Boundary): plan_file=None, engine=None으로 생성 → 정상 생성"""
    wf = Workflow(slug="test-null-plan", plan_file=None, engine=None, status=STATUS_PLANNED, created_at=datetime.now())
    session.add(wf)
    session.commit()
    session.refresh(wf)

    assert wf.id is not None
    assert wf.plan_file is None
    assert wf.engine is None


def test_workflow_model_boundary_duplicate_slug(session):
    """B(Boundary): 동일 slug 중복 INSERT → IntegrityError 발생"""
    wf1 = Workflow(slug="duplicate-slug", status=STATUS_PLANNED, created_at=datetime.now())
    session.add(wf1)
    session.commit()

    wf2 = Workflow(slug="duplicate-slug", status=STATUS_PLANNED, created_at=datetime.now())
    session.add(wf2)

    with pytest.raises(IntegrityError):
        session.commit()
