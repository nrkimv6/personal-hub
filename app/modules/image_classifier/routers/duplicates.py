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

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])
logger = logging.getLogger(__name__)

# 실행 중인 detector 참조 (취소용)
_active_detector = None


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

    query = f"SELECT * FROM duplicate_groups {where} ORDER BY id DESC LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

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
    }


@router.get("/folder-analysis")
async def get_folder_analysis(db: Session = Depends(get_db)):
    """pending 그룹의 멤버를 폴더별로 분석"""
    rows = db.execute(text("""
        SELECT dg.id as group_id, dm.file_id, fc.file_path, dm.file_size, dm.resolution, dm.quality_score
        FROM duplicate_groups dg
        JOIN duplicate_members dm ON dg.id = dm.group_id
        JOIN file_classifications fc ON dm.file_id = fc.id
        WHERE dg.status = 'pending'
        ORDER BY dg.id, dm.quality_score DESC
    """)).fetchall()

    from collections import defaultdict
    folder_map = defaultdict(lambda: {"files": [], "group_ids": set()})

    for row in rows:
        fp = row.file_path
        sep_idx = max(fp.rfind('\\'), fp.rfind('/'))
        folder = fp[:sep_idx] if sep_idx >= 0 else fp

        entry = folder_map[folder]
        entry["group_ids"].add(row.group_id)
        entry["files"].append({
            "file_id": row.file_id,
            "file_path": row.file_path,
            "file_size": row.file_size,
            "resolution": row.resolution,
            "quality_score": row.quality_score,
            "group_id": row.group_id,
        })

    folders = []
    for folder_path, data in sorted(folder_map.items(), key=lambda x: -len(x[1]["files"])):
        folders.append({
            "folder_path": folder_path,
            "file_count": len(data["files"]),
            "group_ids": sorted(data["group_ids"]),
            "files": data["files"],
        })

    total_pending = db.execute(text("SELECT COUNT(*) FROM duplicate_groups WHERE status = 'pending'")).scalar()

    return {"folders": folders, "total_pending_groups": total_pending}


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

        deleted_file_ids = []
        for dc in delete_candidates:
            file_path = Path(dc.file_path)
            if file_path.exists():
                try:
                    send2trash(str(file_path))
                    db.execute(
                        text("UPDATE file_classifications SET status = 'moved', moved_path = :trash WHERE id = :fid"),
                        {"fid": dc.file_id, "trash": "휴지통"}
                    )
                    deleted_file_ids.append(dc.file_id)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"파일 삭제 실패: {file_path} - {e}")
                    failed_count += 1

        resolved_count += 1
        details.append({
            "group_id": gid,
            "kept_file_id": keep_file.file_id,
            "deleted_file_ids": deleted_file_ids,
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
        for member in members:
            if member.file_id == request.keep_file_id:
                continue  # 보관 파일은 스킵

            file_path = Path(member.file_path)
            if file_path.exists():
                try:
                    # 휴지통으로 이동
                    send2trash(str(file_path))

                    # DB 상태 업데이트
                    db.execute(
                        text("""
                            UPDATE file_classifications
                            SET status = 'moved', moved_path = :trash
                            WHERE id = :fid
                        """),
                        {"fid": member.file_id, "trash": "휴지통"}
                    )

                    deleted_count += 1

                except Exception as e:
                    print(f"[오류] 파일 삭제 실패: {file_path} - {e}")

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

    deleted_count = 0
    for member in members:
        file_path = Path(member.file_path)
        if file_path.exists():
            try:
                send2trash(str(file_path))
                db.execute(
                    text("UPDATE file_classifications SET status = 'moved', moved_path = :trash WHERE id = :fid"),
                    {"fid": member.file_id, "trash": "휴지통"}
                )
                deleted_count += 1
            except Exception as e:
                logger.error(f"파일 삭제 실패: {file_path} - {e}")

    db.execute(
        text("UPDATE duplicate_groups SET status = 'resolved', kept_file_id = NULL WHERE id = :gid"),
        {"gid": group_id}
    )
    db.commit()

    return {"status": "resolved", "group_id": group_id, "deleted_count": deleted_count}


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

            for member in members:
                if member.file_id == item.keep_file_id:
                    continue
                file_path = Path(member.file_path)
                if file_path.exists():
                    try:
                        send2trash(str(file_path))
                        db.execute(
                            text("UPDATE file_classifications SET status = 'moved', moved_path = :trash WHERE id = :fid"),
                            {"fid": member.file_id, "trash": "휴지통"}
                        )
                    except Exception as e:
                        logger.error(f"파일 삭제 실패: {file_path} - {e}")

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
