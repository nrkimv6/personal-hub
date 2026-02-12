"""
중복 이미지 관리 API

- GET /api/ic/duplicates: 중복 그룹 목록
- GET /api/ic/duplicates/{group_id}: 특정 그룹 조회
- POST /api/ic/duplicates/{group_id}/resolve: 중복 해결 (keep/delete 결정)
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from pathlib import Path
from send2trash import send2trash

from ..database import get_db

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])


class ResolveRequest(BaseModel):
    """중복 해결 요청"""
    keep_file_id: int
    delete_others: bool = True  # True: 나머지 파일 휴지통 이동


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
    query = "SELECT * FROM duplicate_groups WHERE 1=1"
    params = {}

    if status:
        query += " AND status = :status"
        params["status"] = status

    query += " ORDER BY id DESC LIMIT :limit OFFSET :skip"
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
        "total": len(groups),
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

    db.commit()

    return {
        "status": "resolved",
        "group_id": group_id,
        "kept_file_id": request.keep_file_id,
        "deleted_count": deleted_count,
    }
