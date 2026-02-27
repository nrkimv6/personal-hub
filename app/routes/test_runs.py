"""
테스트 실행 이력 API — pytest 자동 실행 결과 조회 및 수동 트리거.
"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.test_run import TestRun, TestResult

router = APIRouter(prefix="/api/v1/test-runs", tags=["test-runs"])

API_PREFIX = "/api/v1"


# ========== Schemas ==========

class TestResultOut(BaseModel):
    id: int
    test_run_id: int
    test_name: str
    status: str
    duration_seconds: Optional[float]
    error_message: Optional[str]
    traceback: Optional[str]
    fix_plan: Optional[str]
    llm_request_id: Optional[int]

    class Config:
        from_attributes = True


class TestRunOut(BaseModel):
    id: int
    started_at: Optional[str]
    finished_at: Optional[str]
    status: str
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: Optional[float]
    triggered_by: str
    test_path: Optional[str]
    log_file_path: Optional[str]
    xml_file_path: Optional[str]
    schedule_run_id: Optional[int]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_ext(cls, obj: TestRun) -> "TestRunOut":
        return cls(
            id=obj.id,
            started_at=obj.started_at.isoformat() if obj.started_at else None,
            finished_at=obj.finished_at.isoformat() if obj.finished_at else None,
            status=obj.status,
            total_tests=obj.total_tests or 0,
            passed=obj.passed or 0,
            failed=obj.failed or 0,
            errors=obj.errors or 0,
            skipped=obj.skipped or 0,
            duration_seconds=obj.duration_seconds,
            triggered_by=obj.triggered_by,
            test_path=obj.test_path,
            log_file_path=obj.log_file_path,
            xml_file_path=obj.xml_file_path,
            schedule_run_id=obj.schedule_run_id,
        )


class TestRunDetail(TestRunOut):
    results: List[TestResultOut] = []


class TriggerRunRequest(BaseModel):
    test_path: str = "tests/"
    extra_args: List[str] = []
    timeout: int = 1800
    auto_fix_plan: bool = True
    provider: str = "claude"
    model: str = ""


class TriggerRunResponse(BaseModel):
    success: bool
    test_run_id: int
    message: str


# ========== Helpers ==========

def _get_run_or_404(db: Session, run_id: int) -> TestRun:
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"TestRun {run_id} not found")
    return run


# ========== Endpoints ==========

@router.get("", response_model=List[TestRunOut])
def list_test_runs(
    status: Optional[str] = Query(None, description="상태 필터 (running/completed/failed)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """테스트 실행 이력 목록 (최신순)."""
    q = db.query(TestRun)
    if status:
        q = q.filter(TestRun.status == status)
    runs = q.order_by(TestRun.started_at.desc()).offset(offset).limit(limit).all()
    return [TestRunOut.from_orm_ext(r) for r in runs]


@router.get("/{run_id}", response_model=TestRunDetail)
def get_test_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    """테스트 실행 상세 (TestResult 포함, duration 오름차순)."""
    run = _get_run_or_404(db, run_id)
    results = (
        db.query(TestResult)
        .filter(TestResult.test_run_id == run_id)
        .order_by(TestResult.duration_seconds.asc())
        .all()
    )
    detail = TestRunDetail.from_orm_ext(run)
    detail.results = [TestResultOut.model_validate(r, from_attributes=True) for r in results]
    return detail


@router.get("/{run_id}/results", response_model=List[TestResultOut])
def list_test_results(
    run_id: int,
    status: Optional[str] = Query(None, description="상태 필터 (passed/failed/error/skipped)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """테스트 결과 목록 (duration 오름차순, 상태 필터 지원)."""
    _get_run_or_404(db, run_id)
    q = db.query(TestResult).filter(TestResult.test_run_id == run_id)
    if status:
        q = q.filter(TestResult.status == status)
    results = q.order_by(TestResult.duration_seconds.asc()).offset(offset).limit(limit).all()
    return results


@router.get("/{run_id}/log")
def get_test_run_log(
    run_id: int,
    max_lines: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """로그 파일 내용 반환 (마지막 max_lines 줄)."""
    run = _get_run_or_404(db, run_id)
    if not run.log_file_path:
        raise HTTPException(status_code=404, detail="Log file not found")
    path = Path(run.log_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {path}")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return {"run_id": run_id, "log": "\n".join(lines), "total_lines": len(lines)}


@router.post("", response_model=TriggerRunResponse)
def trigger_test_run(
    req: TriggerRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """수동 pytest 실행 트리거 (비동기 백그라운드)."""
    from app.services.pytest_runner_service import PytestRunnerService
    from app.database import SessionLocal

    # 실행 중 중복 방지
    active = (
        db.query(TestRun)
        .filter(TestRun.status == TestRun.STATUS_RUNNING)
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"이미 실행 중인 테스트가 있습니다 (run_id={active.id})"
        )

    # TestRun 선점 생성 (running)
    test_run = TestRun(
        status=TestRun.STATUS_RUNNING,
        triggered_by=TestRun.TRIGGERED_BY_API,
        test_path=req.test_path,
        extra_args=json.dumps(req.extra_args, ensure_ascii=False),
    )
    db.add(test_run)
    db.commit()
    db.refresh(test_run)
    run_id = test_run.id

    def _run_in_bg():
        bg_db = SessionLocal()
        try:
            runner = PytestRunnerService(bg_db)
            # 선점된 TestRun을 재사용하지 않고 새로 실행하되, 이미 만들어진 run은 삭제 후 재생성
            # 단순화: run_tests는 내부적으로 새 TestRun을 생성하므로, 기존 run 상태만 갱신
            finished = runner.run_tests(
                test_path=req.test_path,
                extra_args=req.extra_args,
                timeout=req.timeout,
                triggered_by=TestRun.TRIGGERED_BY_API,
            )
            # 선점 run 업데이트 (실제 결과를 선점 run에 반영)
            pre_run = bg_db.query(TestRun).filter(TestRun.id == run_id).first()
            if pre_run:
                pre_run.status = finished.status
                pre_run.finished_at = finished.finished_at
                pre_run.total_tests = finished.total_tests
                pre_run.passed = finished.passed
                pre_run.failed = finished.failed
                pre_run.errors = finished.errors
                pre_run.skipped = finished.skipped
                pre_run.duration_seconds = finished.duration_seconds
                pre_run.log_file_path = finished.log_file_path
                pre_run.xml_file_path = finished.xml_file_path
                bg_db.commit()

            if req.auto_fix_plan and (finished.failed + finished.errors) > 0:
                runner.create_fix_plan_requests(
                    test_run_id=finished.id,
                    provider=req.provider,
                    model=req.model,
                )
        except Exception as exc:
            pre_run = bg_db.query(TestRun).filter(TestRun.id == run_id).first()
            if pre_run:
                pre_run.mark_failed(str(exc))
                bg_db.commit()
        finally:
            bg_db.close()

    background_tasks.add_task(_run_in_bg)

    return TriggerRunResponse(
        success=True,
        test_run_id=run_id,
        message=f"pytest 실행 시작됨 (run_id={run_id})"
    )
