"""
데이터 정합성 검사 API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.services.integrity_check_service import IntegrityCheckService, IssueSeverity

router = APIRouter(prefix="/api/v1/integrity", tags=["integrity"])


@router.get("/check")
async def run_integrity_check(db: Session = Depends(get_db)):
    """
    전체 정합성 검사 실행.

    Returns:
        total_issues: 전체 문제 수
        by_severity: 심각도별 문제 수
        issues: 문제 목록
    """
    service = IntegrityCheckService(db)
    issues = service.run_full_check()

    return {
        'total_issues': len(issues),
        'by_severity': {
            'critical': len([i for i in issues if i.severity == IssueSeverity.CRITICAL.value]),
            'warning': len([i for i in issues if i.severity == IssueSeverity.WARNING.value]),
            'info': len([i for i in issues if i.severity == IssueSeverity.INFO.value]),
        },
        'issues': [i.to_dict() for i in issues]
    }


@router.get("/stats")
async def get_db_stats(db: Session = Depends(get_db)):
    """
    DB 통계 조회.

    Returns:
        tables: 테이블별 레코드 수
        db_size_bytes: DB 파일 크기 (바이트)
        db_size_mb: DB 파일 크기 (MB)
    """
    service = IntegrityCheckService(db)
    return service.get_db_stats()


@router.post("/fix")
async def fix_all_issues(
    dry_run: bool = Query(True, description="True면 미리보기만, False면 실제 수정"),
    db: Session = Depends(get_db)
):
    """
    자동 수정 가능한 모든 문제 수정.

    Args:
        dry_run: True면 미리보기만 (기본값), False면 실제 수정

    Returns:
        total_issues: 전체 문제 수
        fixable_issues: 자동 수정 가능한 문제 수
        results: 수정 결과 목록
        dry_run: 미리보기 여부
    """
    service = IntegrityCheckService(db)
    return service.auto_fix_all(dry_run=dry_run)


@router.post("/fix/{table}/{issue_type}")
async def fix_specific_issue(
    table: str,
    issue_type: str,
    dry_run: bool = Query(True, description="True면 미리보기만, False면 실제 수정"),
    db: Session = Depends(get_db)
):
    """
    특정 테이블의 특정 유형 문제 수정.

    Args:
        table: 테이블명
        issue_type: 문제 유형 (orphan_fk, invalid_status, invalid_date 등)
        dry_run: True면 미리보기만 (기본값), False면 실제 수정

    Returns:
        fixed: 수정 완료 여부
        affected_count: 영향받은 레코드 수
        dry_run: 미리보기 여부
    """
    service = IntegrityCheckService(db)
    issues = service.run_full_check()

    # 해당 문제 찾기
    target = next(
        (i for i in issues if i.table == table and i.issue_type == issue_type),
        None
    )

    if not target:
        return {'error': f'Issue not found: {table}/{issue_type}', 'fixed': False}

    if not target.auto_fixable:
        return {'error': 'This issue is not auto-fixable', 'fixed': False}

    return service.auto_fix(target, dry_run=dry_run)
