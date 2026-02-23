"""
통계 API 엔드포인트

- GET /stats: file_group별 수, status별 수, 총 크기
- GET /stats/pipeline: 파이프라인 단계별 상태
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(tags=["File Classifier - Stats"])


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """전체 통계 조회"""

    # file_group별 수 + 총 크기
    group_rows = db.execute(
        text("""
            SELECT file_group,
                   COUNT(*) as count,
                   SUM(file_size) as total_size
            FROM fc_files
            GROUP BY file_group
            ORDER BY count DESC
        """)
    ).fetchall()

    by_group = [
        {
            "file_group": r.file_group,
            "count": r.count,
            "total_size": r.total_size or 0,
        }
        for r in group_rows
    ]

    # status별 수
    status_rows = db.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM fc_files
            GROUP BY status
            ORDER BY count DESC
        """)
    ).fetchall()

    by_status = [
        {"status": r.status, "count": r.count}
        for r in status_rows
    ]

    # 전체 합계
    total_row = db.execute(
        text("SELECT COUNT(*) as total_count, SUM(file_size) as total_size FROM fc_files")
    ).fetchone()

    return {
        "total_files": total_row.total_count or 0,
        "total_size": total_row.total_size or 0,
        "by_group": by_group,
        "by_status": by_status,
    }


@router.get("/stats/pipeline")
async def get_pipeline_stats(db: Session = Depends(get_db)):
    """파이프라인 단계별 상태"""

    pipeline_stages = [
        ("pending", "스캔 대기"),
        ("metadata_extracted", "메타데이터 추출 완료"),
        ("rule_classified", "규칙 분류 완료"),
        ("llm_classified", "LLM 분류 완료"),
        ("approved", "사용자 승인"),
        ("moved", "이동 완료"),
        ("error", "오류"),
        ("skipped", "스킵"),
    ]

    status_map: dict[str, int] = {}
    rows = db.execute(
        text("SELECT status, COUNT(*) as count FROM fc_files GROUP BY status")
    ).fetchall()
    for r in rows:
        status_map[r.status] = r.count

    total = sum(status_map.values())

    stages = []
    for status, label in pipeline_stages:
        count = status_map.get(status, 0)
        stages.append({
            "status": status,
            "label": label,
            "count": count,
            "percent": round(count / total * 100, 1) if total > 0 else 0.0,
        })

    # 최근 작업 진행 상태
    recent_tasks = db.execute(
        text("""
            SELECT task_type, status, total_items, processed_items, started_at, completed_at
            FROM fc_task_progress
            ORDER BY id DESC
            LIMIT 5
        """)
    ).fetchall()

    tasks = [
        {
            "task_type": r.task_type,
            "status": r.status,
            "total_items": r.total_items,
            "processed_items": r.processed_items,
            "progress_percent": (
                round(r.processed_items / r.total_items * 100, 1)
                if r.total_items and r.total_items > 0 else 0.0
            ),
            "started_at": r.started_at,
            "completed_at": r.completed_at,
        }
        for r in recent_tasks
    ]

    return {
        "total_files": total,
        "pipeline_stages": stages,
        "recent_tasks": tasks,
    }
