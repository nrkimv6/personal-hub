"""
중복 이미지 관리 API

- POST /api/ic/duplicates/detect: 중복 탐지 시작
- GET /api/ic/duplicates/detect/status: 중복 탐지 진행 상태
- GET /api/ic/duplicates: 중복 그룹 목록
- GET /api/ic/duplicates/{group_id}: 특정 그룹 조회
- POST /api/ic/duplicates/{group_id}/resolve: 중복 해결 (keep/delete 결정)
"""

import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from pathlib import Path
from send2trash import send2trash

from ..database import get_db, SessionLocal
from ..workers.task_progress import TaskProgressManager
from ..utils.pagination import apply_pagination

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])
logger = logging.getLogger(__name__)

# 실행 중인 detector 참조 (취소용)
_active_detector = None


def _batch_delete_files(
    db: Session,
    file_ids: list[int],
    file_paths: list[str],
) -> tuple[int, int]:
    """
    파일 리스트를 send2trash로 배치 삭제하고 DB를 IN절로 일괄 업데이트.

    Args:
        db: SQLAlchemy 세션
        file_ids: 삭제 대상 파일 ID 목록 (file_paths와 1:1 대응)
        file_paths: 삭제 대상 파일 경로 목록

    Returns:
        (deleted_count, failed_count)
    """
    if not file_ids:
        return 0, 0

    # 존재하는 파일만 필터링
    existing_paths: list[str] = []
    existing_ids: list[int] = []
    failed_count = 0

    for fid, fpath in zip(file_ids, file_paths):
        if Path(fpath).exists():
            existing_paths.append(fpath)
            existing_ids.append(fid)

    if not existing_paths:
        return 0, 0

    # send2trash 배치 호출 (리스트 한 번에 전달)
    try:
        send2trash(existing_paths)
    except Exception as e:
        logger.error(f"send2trash 배치 삭제 실패: {e}")
        # 개별 재시도
        successfully_deleted: list[int] = []
        for fid, fpath in zip(existing_ids, existing_paths):
            try:
                send2trash(fpath)
                successfully_deleted.append(fid)
            except Exception as e2:
                logger.error(f"파일 삭제 실패: {fpath} - {e2}")
                failed_count += 1
        existing_ids = successfully_deleted

    if not existing_ids:
        return 0, failed_count

    # DB IN절 단일 쿼리 업데이트
    placeholders = ",".join(str(fid) for fid in existing_ids)
    db.execute(
        text(f"""
            UPDATE file_classifications
            SET status = 'moved', moved_path = '휴지통'
            WHERE id IN ({placeholders})
        """)
    )

    return len(existing_ids), failed_count


def _merge_metadata(
    db: Session,
    keep_file_id: int,
    delete_file_ids: list[int],
) -> int:
    """
    삭제 파일들의 메타데이터를 보관 파일로 병합.

    병합 규칙:
    - file_tags: INSERT OR IGNORE (중복 방지)
    - final_category_id: 보관 파일이 NULL이면 삭제 파일 중 non-NULL 사용
    - ai_category_id / ai_confidence: 보관 파일이 NULL이면 삭제 파일 중 max(ai_confidence) 기준
    - importance: high=3 > medium=2 > low=1 기준 MAX 값 적용
    - extracted_date / date_source: 보관 파일이 unknown/NULL이면 신뢰도 높은 값 사용
    - user_date / user_location: 보관 파일이 NULL이면 삭제 파일 것 사용
    - file_attributes: INSERT OR IGNORE (attr_key 중복 방지)

    Returns:
        병합이 실제로 수행된 경우 1, 스킵인 경우 0
    """
    if not delete_file_ids:
        return 0

    placeholders = ",".join(str(fid) for fid in delete_file_ids)

    # 1. file_tags 병합
    db.execute(text(f"""
        INSERT OR IGNORE INTO file_tags (file_id, tag_id)
        SELECT :keep_id, tag_id
        FROM file_tags
        WHERE file_id IN ({placeholders})
    """), {"keep_id": keep_file_id})

    # 2. final_category_id: 보관 파일이 NULL이면 삭제 파일 중 non-NULL 값
    db.execute(text(f"""
        UPDATE file_classifications
        SET final_category_id = (
            SELECT final_category_id FROM file_classifications
            WHERE id IN ({placeholders}) AND final_category_id IS NOT NULL
            LIMIT 1
        )
        WHERE id = :keep_id
          AND final_category_id IS NULL
    """), {"keep_id": keep_file_id})

    # 3. ai_category_id / ai_confidence: 보관 파일이 NULL이면 max(ai_confidence) 기준
    db.execute(text(f"""
        UPDATE file_classifications
        SET
            ai_category_id = (
                SELECT ai_category_id FROM file_classifications
                WHERE id IN ({placeholders}) AND ai_confidence IS NOT NULL
                ORDER BY ai_confidence DESC
                LIMIT 1
            ),
            ai_confidence = (
                SELECT ai_confidence FROM file_classifications
                WHERE id IN ({placeholders}) AND ai_confidence IS NOT NULL
                ORDER BY ai_confidence DESC
                LIMIT 1
            )
        WHERE id = :keep_id
          AND ai_category_id IS NULL
    """), {"keep_id": keep_file_id})

    # 4. importance: high=3 > medium=2 > low=1 기준 MAX 적용
    db.execute(text(f"""
        UPDATE file_classifications
        SET importance = (
            SELECT importance FROM (
                SELECT importance,
                    CASE importance
                        WHEN 'high'   THEN 3
                        WHEN 'medium' THEN 2
                        WHEN 'low'    THEN 1
                        ELSE 0
                    END AS imp_rank
                FROM file_classifications
                WHERE id IN (:keep_id, {placeholders})
                  AND importance IS NOT NULL
                ORDER BY imp_rank DESC
                LIMIT 1
            )
        )
        WHERE id = :keep_id
    """), {"keep_id": keep_file_id})

    # 5. extracted_date / date_source:
    #    date_source 신뢰도 순서: exif_original > exif_digitized > filename > folder_name > file_modified > user_input > unknown
    #    보관 파일이 'unknown' 또는 NULL이면 삭제 파일 중 가장 신뢰도 높은 것으로 교체
    db.execute(text(f"""
        UPDATE file_classifications
        SET
            extracted_date = (
                SELECT extracted_date FROM file_classifications
                WHERE id IN ({placeholders}) AND date_source NOT IN ('unknown') AND extracted_date IS NOT NULL
                ORDER BY CASE date_source
                    WHEN 'exif_original'  THEN 1
                    WHEN 'exif_digitized' THEN 2
                    WHEN 'filename'       THEN 3
                    WHEN 'folder_name'    THEN 4
                    WHEN 'file_modified'  THEN 5
                    WHEN 'user_input'     THEN 6
                    ELSE 99
                END
                LIMIT 1
            ),
            date_source = (
                SELECT date_source FROM file_classifications
                WHERE id IN ({placeholders}) AND date_source NOT IN ('unknown') AND extracted_date IS NOT NULL
                ORDER BY CASE date_source
                    WHEN 'exif_original'  THEN 1
                    WHEN 'exif_digitized' THEN 2
                    WHEN 'filename'       THEN 3
                    WHEN 'folder_name'    THEN 4
                    WHEN 'file_modified'  THEN 5
                    WHEN 'user_input'     THEN 6
                    ELSE 99
                END
                LIMIT 1
            ),
            date_trust_level = (
                SELECT date_trust_level FROM file_classifications
                WHERE id IN ({placeholders}) AND date_source NOT IN ('unknown') AND extracted_date IS NOT NULL
                ORDER BY CASE date_source
                    WHEN 'exif_original'  THEN 1
                    WHEN 'exif_digitized' THEN 2
                    WHEN 'filename'       THEN 3
                    WHEN 'folder_name'    THEN 4
                    WHEN 'file_modified'  THEN 5
                    WHEN 'user_input'     THEN 6
                    ELSE 99
                END
                LIMIT 1
            )
        WHERE id = :keep_id
          AND (date_source = 'unknown' OR date_source IS NULL OR extracted_date IS NULL)
    """), {"keep_id": keep_file_id})

    # 6. user_date / user_location: 보관 파일이 NULL이면 삭제 파일 것 사용
    db.execute(text(f"""
        UPDATE file_classifications
        SET user_date = (
            SELECT user_date FROM file_classifications
            WHERE id IN ({placeholders}) AND user_date IS NOT NULL
            LIMIT 1
        )
        WHERE id = :keep_id
          AND user_date IS NULL
    """), {"keep_id": keep_file_id})

    db.execute(text(f"""
        UPDATE file_classifications
        SET user_location = (
            SELECT user_location FROM file_classifications
            WHERE id IN ({placeholders}) AND user_location IS NOT NULL
            LIMIT 1
        )
        WHERE id = :keep_id
          AND user_location IS NULL
    """), {"keep_id": keep_file_id})

    # 7. file_attributes: INSERT OR IGNORE (attr_key 중복 방지)
    db.execute(text(f"""
        INSERT OR IGNORE INTO file_attributes (file_id, attr_key, attr_value)
        SELECT :keep_id, attr_key, attr_value
        FROM file_attributes
        WHERE file_id IN ({placeholders})
    """), {"keep_id": keep_file_id})

    return 1


class DetectRequest(BaseModel):
    """중복 탐지 요청"""
    resume: bool = True  # True: 이미 처리된 파일 스킵


@router.post("/detect")
async def start_detect_duplicates(
    background_tasks: BackgroundTasks,
    request: Optional[DetectRequest] = None,
    db: Session = Depends(get_db),
):
    """중복 탐지 시작 (백그라운드)"""
    global _active_detector
    if request is None:
        request = DetectRequest()

    # 이미 실행 중인지 확인
    progress_mgr = TaskProgressManager(db)
    running = progress_mgr.get_running('duplicate')
    if running:
        raise HTTPException(status_code=400, detail="중복 탐지가 이미 실행 중입니다.")

    background_tasks.add_task(_run_detect, request.resume)
    return {"message": "중복 탐지 시작", "resume": request.resume}


@router.post("/detect/stop")
async def stop_detect_duplicates():
    """중복 탐지 중지"""
    global _active_detector
    if _active_detector:
        _active_detector.cancel()
        return {"message": "중복 탐지 중지 요청됨"}
    raise HTTPException(status_code=400, detail="실행 중인 중복 탐지가 없습니다.")


@router.get("/detect/status")
async def get_detect_status(db: Session = Depends(get_db)):
    """중복 탐지 진행 상태 조회"""
    progress_mgr = TaskProgressManager(db)
    latest = progress_mgr.get_latest('duplicate')
    if latest:
        return latest
    return {"status": "none", "message": "중복 탐지 이력 없음"}


class ResolveRequest(BaseModel):
    """중복 해결 요청"""
    keep_file_id: int
    delete_others: bool = True  # True: 나머지 파일 휴지통 이동
    category_id: Optional[int] = None  # 보관 파일의 카테고리 설정 (선택)


@router.get("")
async def get_duplicate_groups(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,  # pending/resolved/ignored
    db: Session = Depends(get_db),
):
    """
    중복 그룹 목록 조회

    Returns:
        [{
            "group_id": int,
            "group_hash": str,
            "member_count": int,
            "status": str,
            "kept_file_id": int | null
        }]
    """
    where = "WHERE 1=1"
    params = {}

    if status:
        where += " AND status = :status"
        params["status"] = status

    # 전체 개수 조회
    count_result = db.execute(text(f"SELECT COUNT(*) FROM duplicate_groups {where}"), params).scalar()

    query = apply_pagination(
        f"SELECT * FROM duplicate_groups {where} ORDER BY id DESC",
        params, skip, limit,
    )

    result = db.execute(text(query), params).fetchall()

    groups = []
    for row in result:
        groups.append({
            "group_id": row.id,
            "group_hash": row.group_hash,
            "member_count": row.member_count,
            "status": row.status,
            "kept_file_id": row.kept_file_id,
        })

    return {
        "groups": groups,
        "skip": skip,
        "limit": limit,
        "total": count_result,
        "has_more": skip + len(groups) < count_result,
    }


@router.get("/folder-analysis")
def get_folder_analysis(db: Session = Depends(get_db)):
    """pending 그룹의 멤버를 폴더별로 분석 (요약만 반환, 파일 상세는 별도 엔드포인트)"""
    # 최소한의 컬럼만 조회 (file_size, resolution, quality_score 제외)
    rows = db.execute(text("""
        SELECT dg.id as group_id, fc.file_path
        FROM duplicate_groups dg
        JOIN duplicate_members dm ON dg.id = dm.group_id
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dg.status = 'pending'
    """)).fetchall()

    from collections import defaultdict
    folder_map = defaultdict(lambda: {"file_count": 0, "group_ids": set()})

    for row in rows:
        fp = row.file_path
        sep_idx = max(fp.rfind('\\'), fp.rfind('/'))
        folder = fp[:sep_idx] if sep_idx >= 0 else fp

        entry = folder_map[folder]
        entry["group_ids"].add(row.group_id)
        entry["file_count"] += 1

    folders = []
    for folder_path, data in sorted(folder_map.items(), key=lambda x: -x[1]["file_count"]):
        folders.append({
            "folder_path": folder_path,
            "file_count": data["file_count"],
            "group_ids": sorted(data["group_ids"]),
        })

    total_pending = db.execute(text("SELECT COUNT(*) FROM duplicate_groups WHERE status = 'pending'")).scalar()

    return {"folders": folders, "total_pending_groups": total_pending}


def _escape_like(value: str) -> str:
    """SQLite LIKE 와일드카드 문자를 '!' 이스케이프로 처리"""
    return value.replace('!', '!!').replace('%', '!%').replace('_', '!_')


@router.get("/folder-analysis/files")
def get_folder_analysis_files(
    folder: str,
    db: Session = Depends(get_db),
):
    """특정 폴더 선택 시 보관/삭제 대상 파일 상세 정보 반환"""
    folder_normalized = folder.replace('/', '\\')
    like_backslash = _escape_like(folder_normalized) + '\\%'
    like_slash = _escape_like(folder.replace('\\', '/')) + '/%'

    # 1단계: 이 폴더에 파일이 있는 pending 그룹 ID 찾기
    group_rows = db.execute(text("""
        SELECT DISTINCT dm.group_id
        FROM duplicate_members dm
        JOIN file_classifications fc ON dm.file_id = fc.id
        JOIN duplicate_groups dg ON dm.group_id = dg.id
        WHERE dg.status = 'pending'
        AND (fc.file_path LIKE :like_bs ESCAPE '!' OR fc.file_path LIKE :like_sl ESCAPE '!')
    """), {"like_bs": like_backslash, "like_sl": like_slash}).fetchall()

    group_ids = [r.group_id for r in group_rows]
    if not group_ids:
        return {"keep_files": [], "delete_files": [], "group_ids": []}

    # 2단계: 해당 그룹들의 모든 멤버 조회
    placeholders = ",".join(str(gid) for gid in group_ids)
    rows = db.execute(text(f"""
        SELECT dg.id as group_id, dm.file_id, fc.file_path, dm.file_size, dm.resolution, dm.quality_score
        FROM duplicate_groups dg
        JOIN duplicate_members dm ON dg.id = dm.group_id
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dg.id IN ({placeholders})
        ORDER BY dg.id, dm.quality_score DESC
    """)).fetchall()

    keep_files = []
    delete_files = []
    for row in rows:
        fp_normalized = row.file_path.replace('/', '\\')
        sep_idx = max(fp_normalized.rfind('\\'), fp_normalized.rfind('/'))
        m_folder = fp_normalized[:sep_idx] if sep_idx >= 0 else fp_normalized

        file_info = {
            "file_id": row.file_id,
            "file_path": row.file_path,
            "file_size": row.file_size,
            "resolution": row.resolution,
            "quality_score": row.quality_score,
            "group_id": row.group_id,
        }

        if m_folder == folder_normalized:
            keep_files.append(file_info)
        else:
            delete_files.append(file_info)

    return {"keep_files": keep_files, "delete_files": delete_files, "group_ids": sorted(group_ids)}


class ResolveByFolderRequest(BaseModel):
    keep_folder: str
    group_ids: list[int]


@router.post("/resolve-by-folder")
async def resolve_by_folder(
    request: ResolveByFolderRequest,
    db: Session = Depends(get_db),
):
    """폴더 기준 일괄 해결: keep_folder의 파일 보관, 나머지 삭제"""
    resolved_count = 0
    deleted_count = 0
    skipped_count = 0
    failed_count = 0
    details = []

    keep_folder_normalized = request.keep_folder.replace('/', '\\')

    for gid in request.group_ids:
        members = db.execute(
            text("""
                SELECT dm.file_id, fc.file_path, dm.quality_score
                FROM duplicate_members dm
                JOIN file_classifications fc ON dm.file_id = fc.id
                WHERE dm.group_id = :gid
            """),
            {"gid": gid}
        ).fetchall()

        if not members:
            skipped_count += 1
            continue

        # keep_folder에 속한 파일 찾기
        keep_candidates = []
        delete_candidates = []
        for m in members:
            fp_normalized = m.file_path.replace('/', '\\')
            sep_idx = max(fp_normalized.rfind('\\'), fp_normalized.rfind('/'))
            m_folder = fp_normalized[:sep_idx] if sep_idx >= 0 else fp_normalized

            if m_folder == keep_folder_normalized:
                keep_candidates.append(m)
            else:
                delete_candidates.append(m)

        if not keep_candidates:
            skipped_count += 1
            continue

        # quality_score 가장 높은 것 보관
        keep_file = max(keep_candidates, key=lambda x: x.quality_score or 0)
        # keep_candidates 중 보관 파일 외의 것도 삭제 대상에 추가
        for kc in keep_candidates:
            if kc.file_id != keep_file.file_id:
                delete_candidates.append(kc)

        db.execute(
            text("UPDATE duplicate_groups SET status = 'resolved', kept_file_id = :keep_id WHERE id = :gid"),
            {"gid": gid, "keep_id": keep_file.file_id}
        )

        delete_ids = [dc.file_id for dc in delete_candidates]
        delete_paths = [dc.file_path for dc in delete_candidates]
        _merge_metadata(db, keep_file.file_id, delete_ids)
        batch_deleted, batch_failed = _batch_delete_files(db, delete_ids, delete_paths)
        deleted_count += batch_deleted
        failed_count += batch_failed

        resolved_count += 1
        details.append({
            "group_id": gid,
            "kept_file_id": keep_file.file_id,
            "deleted_file_ids": delete_ids,
        })

    db.commit()

    return {
        "resolved_count": resolved_count,
        "deleted_count": deleted_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "details": details,
    }


@router.get("/{group_id}")
async def get_duplicate_group_detail(
    group_id: int,
    db: Session = Depends(get_db),
):
    """
    특정 중복 그룹의 상세 정보 조회

    Returns:
        {
            "group_id": int,
            "group_hash": str,
            "member_count": int,
            "status": str,
            "members": [
                {
                    "file_id": int,
                    "file_path": str,
                    "file_size": int,
                    "resolution": str,
                    "quality_score": float,
                    "phash_distance": int,
                    "is_exact": bool
                }
            ]
        }
    """
    # 그룹 정보 조회
    group = db.execute(
        text("SELECT * FROM duplicate_groups WHERE id = :gid"),
        {"gid": group_id}
    ).fetchone()

    if not group:
        raise HTTPException(status_code=404, detail="중복 그룹을 찾을 수 없습니다.")

    # 멤버 조회
    members = db.execute(
        text("""
            SELECT
                dm.file_id, dm.phash_distance, dm.is_exact,
                dm.file_size, dm.resolution, dm.quality_score,
                fc.file_path
            FROM duplicate_members dm
            JOIN file_classifications fc ON dm.file_id = fc.id
            WHERE dm.group_id = :gid
            ORDER BY dm.quality_score DESC
        """),
        {"gid": group_id}
    ).fetchall()

    member_list = []
    for row in members:
        member_list.append({
            "file_id": row.file_id,
            "file_path": row.file_path,
            "file_size": row.file_size,
            "resolution": row.resolution,
            "quality_score": row.quality_score,
            "phash_distance": row.phash_distance,
            "is_exact": row.is_exact,
        })

    return {
        "group_id": group.id,
        "group_hash": group.group_hash,
        "member_count": group.member_count,
        "status": group.status,
        "members": member_list,
    }


@router.post("/{group_id}/resolve")
async def resolve_duplicate_group(
    group_id: int,
    request: ResolveRequest,
    db: Session = Depends(get_db),
):
    """
    중복 그룹 해결 (대표 이미지 선택 + 나머지 삭제)

    Args:
        group_id: 중복 그룹 ID
        request: 보관할 파일 ID, 나머지 삭제 여부

    Returns:
        {"status": "resolved", "kept_file_id": int, "deleted_count": int}
    """
    # 그룹 멤버 조회
    members = db.execute(
        text("""
            SELECT dm.file_id, fc.file_path
            FROM duplicate_members dm
            JOIN file_classifications fc ON dm.file_id = fc.id
            WHERE dm.group_id = :gid
        """),
        {"gid": group_id}
    ).fetchall()

    if not members:
        raise HTTPException(status_code=404, detail="중복 그룹을 찾을 수 없습니다.")

    # keep_file_id 검증
    keep_file_ids = [m.file_id for m in members]
    if request.keep_file_id not in keep_file_ids:
        raise HTTPException(
            status_code=400,
            detail=f"보관할 파일 ID({request.keep_file_id})가 그룹 멤버가 아닙니다."
        )

    # 그룹 상태 업데이트
    db.execute(
        text("""
            UPDATE duplicate_groups
            SET status = 'resolved', kept_file_id = :keep_id
            WHERE id = :gid
        """),
        {"gid": group_id, "keep_id": request.keep_file_id}
    )

    deleted_count = 0

    # 나머지 파일 삭제 (선택)
    if request.delete_others:
        delete_ids = [m.file_id for m in members if m.file_id != request.keep_file_id]
        delete_paths = [m.file_path for m in members if m.file_id != request.keep_file_id]
        _merge_metadata(db, request.keep_file_id, delete_ids)
        deleted_count, _ = _batch_delete_files(db, delete_ids, delete_paths)

    # 보관 파일에 카테고리 설정 (선택)
    if request.category_id is not None:
        db.execute(
            text("""
                UPDATE file_classifications
                SET final_category_id = :cat_id
                WHERE id = :fid
            """),
            {"cat_id": request.category_id, "fid": request.keep_file_id}
        )

    db.commit()

    return {
        "status": "resolved",
        "group_id": group_id,
        "kept_file_id": request.keep_file_id,
        "category_id": request.category_id,
        "deleted_count": deleted_count,
    }


@router.post("/{group_id}/discard-all")
async def discard_all_in_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """그룹의 모든 멤버를 휴지통으로 이동 (보관 없이)"""
    members = db.execute(
        text("""
            SELECT dm.file_id, fc.file_path
            FROM duplicate_members dm
            JOIN file_classifications fc ON dm.file_id = fc.id
            WHERE dm.group_id = :gid
        """),
        {"gid": group_id}
    ).fetchall()

    if not members:
        raise HTTPException(status_code=404, detail="중복 그룹을 찾을 수 없습니다.")

    delete_ids = [m.file_id for m in members]
    delete_paths = [m.file_path for m in members]
    deleted_count, _ = _batch_delete_files(db, delete_ids, delete_paths)

    db.execute(
        text("UPDATE duplicate_groups SET status = 'resolved', kept_file_id = NULL WHERE id = :gid"),
        {"gid": group_id}
    )
    db.commit()

    return {"status": "resolved", "group_id": group_id, "deleted_count": deleted_count}


def _select_keep_file(
    members: list,
    strategy: str = "quality_best",
) -> tuple[int, str]:
    """
    멤버 목록에서 자동 선택 로직 실행.

    Returns:
        (auto_keep_file_id, confidence)
        confidence: "high" | "medium" | "low"
    """
    if not members:
        return members[0]["file_id"], "low"

    # exact 여부: 모든 멤버가 is_exact=True이면 exact 그룹
    is_exact_group = all(m.get("is_exact", False) for m in members)

    if strategy == "largest_file":
        # near도 크기 기준
        best = max(members, key=lambda m: m.get("file_size") or 0)
        confidence = "high" if is_exact_group else "medium"
        return best["file_id"], confidence

    # quality_best 전략 (기본)
    if is_exact_group:
        sizes = [m.get("file_size") or 0 for m in members]
        if len(set(sizes)) > 1:
            # 크기 차이 있음 → largest_file 자동 선택, confidence=high
            best = max(members, key=lambda m: m.get("file_size") or 0)
            return best["file_id"], "high"
        else:
            # 크기 동일 → 첫 번째, confidence=low
            return members[0]["file_id"], "low"
    else:
        # near 그룹 → quality_score 기반
        best = max(members, key=lambda m: m.get("quality_score") or 0)
        return best["file_id"], "medium"


@router.get("/review")
async def get_review(
    skip: int = 0,
    limit: int = 100,
    filter: str = "all",  # exact/near/all
    auto_strategy: str = "quality_best",  # quality_best/largest_file
    db: Session = Depends(get_db),
):
    """
    중복 그룹 Review API — pending 그룹 + 멤버 + 자동선택을 한번에 반환 (N+1 없음)

    Returns:
        {
            "groups": [{
                "group_id", "group_hash", "member_count", "status",
                "auto_keep_file_id", "confidence",
                "members": [{"file_id","file_path","file_size","resolution","quality_score","phash_distance","is_exact"}]
            }],
            "skip", "limit", "total",
            "auto_resolvable": confidence=high 수,
            "needs_review": confidence=low 수
        }
    """
    where = "WHERE dg.status = 'pending'"
    params: dict = {}

    if filter == "exact":
        where += " AND dm.is_exact = 1"
    elif filter == "near":
        where += " AND dm.is_exact = 0"

    # 전체 pending 그룹 수 (filter 조건 적용)
    if filter == "all":
        count_result = db.execute(
            text("SELECT COUNT(*) FROM duplicate_groups WHERE status = 'pending'")
        ).scalar() or 0
    else:
        is_exact_val = 1 if filter == "exact" else 0
        count_result = db.execute(
            text("""
                SELECT COUNT(DISTINCT dg.id) FROM duplicate_groups dg
                JOIN duplicate_members dm ON dg.id = dm.group_id
                WHERE dg.status = 'pending' AND dm.is_exact = :is_exact
            """),
            {"is_exact": is_exact_val}
        ).scalar() or 0

    # pending 그룹 ID 페이지네이션 (서브쿼리)
    if filter == "all":
        group_ids_rows = db.execute(
            text(f"""
                SELECT id FROM duplicate_groups WHERE status = 'pending'
                ORDER BY id DESC
                LIMIT :limit OFFSET :skip
            """),
            {"limit": limit, "skip": skip}
        ).fetchall()
    else:
        is_exact_val = 1 if filter == "exact" else 0
        group_ids_rows = db.execute(
            text(f"""
                SELECT DISTINCT dg.id FROM duplicate_groups dg
                JOIN duplicate_members dm ON dg.id = dm.group_id
                WHERE dg.status = 'pending' AND dm.is_exact = :is_exact
                ORDER BY dg.id DESC
                LIMIT :limit OFFSET :skip
            """),
            {"is_exact": is_exact_val, "limit": limit, "skip": skip}
        ).fetchall()

    page_group_ids = [r.id for r in group_ids_rows]

    if not page_group_ids:
        return {
            "groups": [],
            "skip": skip,
            "limit": limit,
            "total": count_result,
            "auto_resolvable": 0,
            "needs_review": 0,
        }

    # 단일 JOIN 쿼리로 그룹 + 멤버 + file_path 일괄 조회
    placeholders = ",".join(str(gid) for gid in page_group_ids)
    rows = db.execute(text(f"""
        SELECT
            dg.id        AS group_id,
            dg.group_hash,
            dg.member_count,
            dg.status,
            dm.file_id,
            dm.phash_distance,
            dm.is_exact,
            dm.file_size,
            dm.resolution,
            dm.quality_score,
            fc.file_path
        FROM duplicate_groups dg
        JOIN duplicate_members dm ON dg.id = dm.group_id
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dg.id IN ({placeholders})
        ORDER BY dg.id DESC, dm.quality_score DESC
    """)).fetchall()

    # Python에서 그룹별 멤버 집합 구성
    from collections import OrderedDict
    group_map: dict = OrderedDict()
    for row in rows:
        gid = row.group_id
        if gid not in group_map:
            group_map[gid] = {
                "group_id": gid,
                "group_hash": row.group_hash,
                "member_count": row.member_count,
                "status": row.status,
                "members": [],
            }
        group_map[gid]["members"].append({
            "file_id": row.file_id,
            "file_path": row.file_path,
            "file_size": row.file_size,
            "resolution": row.resolution,
            "quality_score": row.quality_score,
            "phash_distance": row.phash_distance,
            "is_exact": bool(row.is_exact),
        })

    # 각 그룹별 auto_keep_file_id + confidence 계산
    auto_resolvable = 0
    needs_review = 0
    groups = []
    for gid, gdata in group_map.items():
        keep_id, confidence = _select_keep_file(gdata["members"], auto_strategy)
        gdata["auto_keep_file_id"] = keep_id
        gdata["confidence"] = confidence
        if confidence == "high":
            auto_resolvable += 1
        elif confidence == "low":
            needs_review += 1
        groups.append(gdata)

    return {
        "groups": groups,
        "skip": skip,
        "limit": limit,
        "total": count_result,
        "auto_resolvable": auto_resolvable,
        "needs_review": needs_review,
    }


class AutoResolveRequest(BaseModel):
    filter: str = "all"  # exact/near/all
    strategy: str = "quality_best"  # quality_best/largest_file
    group_ids: list[int] = []  # 비어있으면 해당 filter의 모든 pending
    exclude_group_ids: list[int] = []


@router.post("/auto-resolve")
async def auto_resolve(
    request: AutoResolveRequest,
    db: Session = Depends(get_db),
):
    """
    자동선택 로직으로 중복 그룹 일괄 해결.

    - group_ids 비어있으면 filter 조건의 모든 pending 그룹 처리
    - exclude_group_ids에 포함된 그룹은 제외
    - 각 그룹: _merge_metadata → _batch_delete_files → status='resolved'
    """
    # 대상 그룹 ID 결정
    if request.group_ids:
        candidate_ids = request.group_ids
    else:
        # filter 조건의 모든 pending 그룹 조회
        if request.filter == "all":
            rows = db.execute(
                text("SELECT id FROM duplicate_groups WHERE status = 'pending'")
            ).fetchall()
        else:
            is_exact_val = 1 if request.filter == "exact" else 0
            rows = db.execute(
                text("""
                    SELECT DISTINCT dg.id FROM duplicate_groups dg
                    JOIN duplicate_members dm ON dg.id = dm.group_id
                    WHERE dg.status = 'pending' AND dm.is_exact = :is_exact
                """),
                {"is_exact": is_exact_val}
            ).fetchall()
        candidate_ids = [r.id for r in rows]

    # exclude 적용
    exclude_set = set(request.exclude_group_ids)
    target_ids = [gid for gid in candidate_ids if gid not in exclude_set]

    resolved = 0
    deleted_files = 0
    merged_metadata = 0
    failed = 0

    for gid in target_ids:
        try:
            members = db.execute(
                text("""
                    SELECT dm.file_id, dm.is_exact, dm.file_size, dm.quality_score, fc.file_path
                    FROM duplicate_members dm
                    JOIN file_classifications fc ON dm.file_id = fc.id
                    WHERE dm.group_id = :gid
                """),
                {"gid": gid}
            ).fetchall()

            if not members:
                failed += 1
                continue

            member_list = [
                {
                    "file_id": m.file_id,
                    "file_path": m.file_path,
                    "file_size": m.file_size,
                    "quality_score": m.quality_score,
                    "is_exact": bool(m.is_exact),
                }
                for m in members
            ]

            keep_id, _confidence = _select_keep_file(member_list, request.strategy)

            delete_ids = [m["file_id"] for m in member_list if m["file_id"] != keep_id]
            delete_paths = [m["file_path"] for m in member_list if m["file_id"] != keep_id]

            merged_metadata += _merge_metadata(db, keep_id, delete_ids)
            batch_deleted, _ = _batch_delete_files(db, delete_ids, delete_paths)
            deleted_files += batch_deleted

            db.execute(
                text("UPDATE duplicate_groups SET status = 'resolved', kept_file_id = :keep_id WHERE id = :gid"),
                {"gid": gid, "keep_id": keep_id}
            )
            resolved += 1

        except Exception as e:
            logger.error(f"auto_resolve group {gid}: {e}")
            failed += 1

    db.commit()

    return {
        "resolved": resolved,
        "deleted_files": deleted_files,
        "merged_metadata": merged_metadata,
        "failed": failed,
    }


class BulkResolveItem(BaseModel):
    group_id: int
    keep_file_id: int


class BulkResolveRequest(BaseModel):
    resolutions: list[BulkResolveItem]


@router.post("/bulk-resolve")
async def bulk_resolve(
    request: BulkResolveRequest,
    db: Session = Depends(get_db),
):
    """여러 그룹 일괄 확정 (keep 파일 보관, 나머지 휴지통)"""
    resolved = 0
    failed = 0
    errors: list[str] = []
    resolved_group_ids: list[int] = []

    for item in request.resolutions:
        try:
            members = db.execute(
                text("""
                    SELECT dm.file_id, fc.file_path
                    FROM duplicate_members dm
                    JOIN file_classifications fc ON dm.file_id = fc.id
                    WHERE dm.group_id = :gid
                """),
                {"gid": item.group_id}
            ).fetchall()

            if not members:
                errors.append(f"Group {item.group_id}: 멤버 없음")
                failed += 1
                continue

            member_ids = [m.file_id for m in members]
            if item.keep_file_id not in member_ids:
                errors.append(f"Group {item.group_id}: keep_file_id {item.keep_file_id}가 멤버가 아님")
                failed += 1
                continue

            db.execute(
                text("UPDATE duplicate_groups SET status = 'resolved', kept_file_id = :keep_id WHERE id = :gid"),
                {"gid": item.group_id, "keep_id": item.keep_file_id}
            )

            delete_ids = [m.file_id for m in members if m.file_id != item.keep_file_id]
            delete_paths = [m.file_path for m in members if m.file_id != item.keep_file_id]
            _merge_metadata(db, item.keep_file_id, delete_ids)
            _batch_delete_files(db, delete_ids, delete_paths)

            resolved += 1
            resolved_group_ids.append(item.group_id)

        except Exception as e:
            errors.append(f"Group {item.group_id}: {str(e)}")
            failed += 1

    db.commit()

    return {
        "resolved": resolved,
        "failed": failed,
        "errors": errors,
        "resolved_group_ids": resolved_group_ids,
    }


class MergeGroupsRequest(BaseModel):
    """그룹 병합 요청"""
    group_ids: list[int]


@router.post("/merge")
async def merge_duplicate_groups(
    request: MergeGroupsRequest,
    db: Session = Depends(get_db),
):
    """
    여러 중복 그룹을 첫 번째 그룹으로 병합

    - 선택 그룹 멤버를 첫 번째 그룹에 합치기
    - 나머지 그룹은 'merged' 상태로 변경
    - member_count, quality_score 재계산
    """
    if len(request.group_ids) < 2:
        raise HTTPException(status_code=400, detail="병합하려면 2개 이상의 그룹이 필요합니다.")

    target_group_id = request.group_ids[0]
    source_group_ids = request.group_ids[1:]

    # 대상 그룹 확인
    target_group = db.execute(
        text("SELECT id, status FROM duplicate_groups WHERE id = :gid"),
        {"gid": target_group_id}
    ).fetchone()
    if not target_group:
        raise HTTPException(status_code=404, detail=f"그룹 {target_group_id}을 찾을 수 없습니다.")

    # 소스 그룹 멤버를 대상 그룹으로 이동
    total_moved = 0
    for src_group_id in source_group_ids:
        # 소스 그룹 멤버 조회
        members = db.execute(
            text("SELECT file_id FROM duplicate_members WHERE group_id = :gid"),
            {"gid": src_group_id}
        ).fetchall()

        for member in members:
            # 이미 대상 그룹에 있는지 확인
            existing = db.execute(
                text("SELECT 1 FROM duplicate_members WHERE group_id = :gid AND file_id = :fid"),
                {"gid": target_group_id, "fid": member.file_id}
            ).fetchone()

            if not existing:
                # 대상 그룹으로 이동
                db.execute(
                    text("""
                        UPDATE duplicate_members
                        SET group_id = :target_id
                        WHERE group_id = :src_id AND file_id = :fid
                    """),
                    {"target_id": target_group_id, "src_id": src_group_id, "fid": member.file_id}
                )
                total_moved += 1
            else:
                # 중복 멤버 삭제
                db.execute(
                    text("DELETE FROM duplicate_members WHERE group_id = :gid AND file_id = :fid"),
                    {"gid": src_group_id, "fid": member.file_id}
                )

        # 소스 그룹을 'merged' 상태로 변경
        db.execute(
            text("UPDATE duplicate_groups SET status = 'merged' WHERE id = :gid"),
            {"gid": src_group_id}
        )

    # 대상 그룹의 member_count 재계산
    new_count = db.execute(
        text("SELECT COUNT(*) FROM duplicate_members WHERE group_id = :gid"),
        {"gid": target_group_id}
    ).scalar() or 0

    db.execute(
        text("UPDATE duplicate_groups SET member_count = :cnt WHERE id = :gid"),
        {"cnt": new_count, "gid": target_group_id}
    )

    db.commit()

    return {
        "status": "merged",
        "target_group_id": target_group_id,
        "merged_group_ids": source_group_ids,
        "new_member_count": new_count,
        "members_moved": total_moved,
        "message": f"{len(source_group_ids)}개 그룹을 그룹 {target_group_id}으로 병합 완료"
    }


@router.post("/{group_id}/keep-all")
async def keep_all_in_group(
    group_id: int,
    db: Session = Depends(get_db),
):
    """
    그룹의 모든 멤버를 보관 (삭제 없이 해결)

    - 그룹 상태 → 'resolved', resolution_type = 'keep_all', kept_file_id = NULL
    - 멤버 파일의 삭제 예정 플래그 해제 (status가 pending 상태인 것 유지)
    """
    group = db.execute(
        text("SELECT id, status FROM duplicate_groups WHERE id = :gid"),
        {"gid": group_id}
    ).fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="중복 그룹을 찾을 수 없습니다.")

    # 그룹 상태를 resolved로 변경 (kept_file_id = NULL = 모두 보관)
    db.execute(
        text("""
            UPDATE duplicate_groups
            SET status = 'resolved', kept_file_id = NULL
            WHERE id = :gid
        """),
        {"gid": group_id}
    )

    # 멤버 수 조회
    member_count = db.execute(
        text("SELECT COUNT(*) FROM duplicate_members WHERE group_id = :gid"),
        {"gid": group_id}
    ).scalar() or 0

    db.commit()

    return {
        "status": "resolved",
        "resolution_type": "keep_all",
        "group_id": group_id,
        "kept_count": member_count,
        "message": f"그룹 {group_id}의 {member_count}개 파일 모두 보관 처리"
    }


def _run_detect(resume: bool):
    """백그라운드 중복 탐지 실행 (동기 → 스레드 풀에서 실행)"""
    global _active_detector

    from ..config import ImageClassifierSettings
    settings = ImageClassifierSettings()
    db = SessionLocal()
    progress_db = SessionLocal()

    from ..workers.log_buffer import pipeline_logs

    try:
        from ..workers.duplicate_detector import DuplicateDetector
        detector = DuplicateDetector(db, settings)
        _active_detector = detector
        pipeline_logs.add("duplicate", "[중복 감지] 시작")
        detector.detect_duplicates_sync(resume=resume, progress_db=progress_db)
        pipeline_logs.add("duplicate", "[중복 감지] 완료")
    except Exception as e:
        msg = f"[중복 감지] 오류: {e}"
        logger.error(msg)
        pipeline_logs.add("duplicate", msg)
    finally:
        _active_detector = None
        db.close()
        progress_db.close()
