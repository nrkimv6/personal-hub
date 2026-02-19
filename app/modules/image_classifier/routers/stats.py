"""
이미지 분류 통계 API 라우터

- GET /api/ic/stats          : 전체 통계 (카드 4개 + 카테고리 분포)
- GET /api/ic/stats/tasks    : 백그라운드 태스크 상태 (StatusBar)
- GET /api/ic/stats/activity : 최근 활동 피드 (Dashboard)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from ..database import get_db

router = APIRouter(prefix="/stats", tags=["Image Classifier - Stats"])


# =========================================================
# GET /api/ic/stats
# =========================================================

@router.get("")
async def get_stats(db: Session = Depends(get_db)):
    """
    대시보드 통계 카드 데이터 반환

    Returns:
        total_images     : file_classifications 전체 행 수
        classified       : status IN (ai_classified, approved, moved)
        duplicates       : 동일 file_hash 그룹 수 (hash 기준 중복)
        clusters         : time_clusters 행 수
        category_distribution : [{name, count, pct}]
    """

    # 전체 이미지 수
    total_row = db.execute(text(
        "SELECT COUNT(*) as cnt FROM file_classifications"
    )).fetchone()
    total_images = total_row.cnt if total_row else 0

    # 분류 완료 수 (ai_classified, approved, moved)
    classified_row = db.execute(text("""
        SELECT COUNT(*) as cnt FROM file_classifications
        WHERE status IN ('ai_classified', 'approved', 'moved')
    """)).fetchone()
    classified = classified_row.cnt if classified_row else 0

    # 중복 해시 그룹 수
    dup_row = db.execute(text("""
        SELECT COUNT(*) as cnt FROM (
            SELECT file_hash
            FROM file_classifications
            WHERE file_hash IS NOT NULL AND file_hash != ''
            GROUP BY file_hash
            HAVING COUNT(*) > 1
        )
    """)).fetchone()
    duplicates = dup_row.cnt if dup_row else 0

    # 타임 클러스터 수
    cluster_row = db.execute(text(
        "SELECT COUNT(*) as cnt FROM time_clusters"
    )).fetchone()
    clusters = cluster_row.cnt if cluster_row else 0

    # 카테고리 분포 (분류된 파일만, 상위 10개)
    cat_rows = db.execute(text("""
        SELECT c.name, COUNT(*) as cnt
        FROM file_classifications fc
        JOIN categories c ON c.id = fc.final_category_id
        WHERE fc.final_category_id IS NOT NULL
        GROUP BY c.id, c.name
        ORDER BY cnt DESC
        LIMIT 10
    """)).fetchall()

    # 분류된 파일 총 수 (분포 계산용)
    classified_total = sum(r.cnt for r in cat_rows) if cat_rows else 1

    category_distribution = [
        {
            "name": r.name,
            "count": r.cnt,
            "pct": round(r.cnt / classified_total * 100) if classified_total > 0 else 0,
        }
        for r in cat_rows
    ]

    return {
        "total_images": total_images,
        "classified": classified,
        "duplicates": duplicates,
        "clusters": clusters,
        "category_distribution": category_distribution,
    }


# =========================================================
# GET /api/ic/stats/tasks
# =========================================================

@router.get("/tasks")
async def get_tasks():
    """
    백그라운드 태스크 현황 반환 (StatusBar 용)

    classify.py의 classification_status 전역 변수를 재활용.
    실행 중인 태스크 없으면 빈 배열 반환.

    Returns:
        tasks: [{id, name, status, progress}]
    """
    from .classify import classification_status

    tasks = []

    if classification_status.get("running"):
        total = classification_status.get("total", 0)
        processed = classification_status.get("processed", 0)
        progress = round(processed / total * 100) if total > 0 else 0
        model = classification_status.get("model", "AI")

        tasks.append({
            "id": 1,
            "name": f"AI Classification ({model})",
            "status": "running",
            "progress": progress,
        })

    return {"tasks": tasks}


# =========================================================
# GET /api/ic/stats/activity
# =========================================================

@router.get("/activity")
async def get_activity(
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """
    최근 활동 피드 반환 (Dashboard Recent Activity 용)

    file_classifications의 classified_at, approved_at, moved_at을
    UNION해서 시간순으로 정렬 반환.

    Returns:
        activity: [{id, time_ago, message, type, ts}]
    """
    rows = db.execute(text("""
        SELECT event_type, file_path, event_ts
        FROM (
            SELECT 'classified' as event_type,
                   file_path,
                   classified_at as event_ts
            FROM file_classifications
            WHERE classified_at IS NOT NULL

            UNION ALL

            SELECT 'approved' as event_type,
                   file_path,
                   approved_at as event_ts
            FROM file_classifications
            WHERE approved_at IS NOT NULL

            UNION ALL

            SELECT 'moved' as event_type,
                   file_path,
                   moved_at as event_ts
            FROM file_classifications
            WHERE moved_at IS NOT NULL
        )
        ORDER BY event_ts DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()

    import re
    from datetime import datetime, timezone

    def _time_ago(ts_str: Optional[str]) -> str:
        """'YYYY-MM-DD HH:MM:SS' → '3분 전' 형태 반환"""
        if not ts_str:
            return ""
        try:
            # SQLite의 datetime('now') 는 UTC, naive datetime
            dt = datetime.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S")
            now = datetime.utcnow()
            diff = int((now - dt).total_seconds())
            if diff < 60:
                return f"{diff}초 전"
            elif diff < 3600:
                return f"{diff // 60}분 전"
            elif diff < 86400:
                return f"{diff // 3600}시간 전"
            else:
                return f"{diff // 86400}일 전"
        except Exception:
            return str(ts_str)[:16]

    def _message(event_type: str, file_path: str) -> str:
        basename = file_path.split("/")[-1].split("\\")[-1] if file_path else "파일"
        if event_type == "classified":
            return f"AI 분류 완료: {basename}"
        elif event_type == "approved":
            return f"승인됨: {basename}"
        elif event_type == "moved":
            return f"이동됨: {basename}"
        return f"{event_type}: {basename}"

    activity = []
    for i, row in enumerate(rows):
        activity.append({
            "id": i + 1,
            "time": _time_ago(row.event_ts),
            "message": _message(row.event_type, row.file_path or ""),
            "type": "info",
            "ts": str(row.event_ts),
        })

    return {"activity": activity}
