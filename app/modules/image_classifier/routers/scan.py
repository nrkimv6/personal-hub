"""
스캔 관련 API 엔드포인트

- POST /api/ic/scan/start: 폴더 트리 스캔 시작
- GET /api/ic/scan/status: 스캔 진행 상태 조회
- GET /api/ic/scan/folders: 폴더 목록 조회
"""

import asyncio
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..workers.scanner import FolderScanner
from ..config import settings

router = APIRouter(prefix="/scan", tags=["Scan"])


# === 요청/응답 스키마 ===
class ScanStartRequest(BaseModel):
    """스캔 시작 요청"""
    root_folders: Optional[list[str]] = None  # None이면 config의 SCAN_ROOT_FOLDERS 사용


class ScanStatusResponse(BaseModel):
    """스캔 상태 응답"""
    is_running: bool
    total_folders: int
    scanned_folders: int
    total_files: int
    scanned_files: int
    progress_percent: float
    current_folder: Optional[str]
    error: Optional[str]


class FolderInfoResponse(BaseModel):
    """폴더 정보 응답"""
    id: int
    folder_path: str
    file_count: int
    folder_status: str  # clear/unclear/flat/nested
    category_id: Optional[int]
    is_mixed: bool


# === 전역 스캔 상태 ===
scan_state = {
    "is_running": False,
    "total_folders": 0,
    "scanned_folders": 0,
    "total_files": 0,
    "scanned_files": 0,
    "current_folder": None,
    "error": None,
}


# === 엔드포인트 ===
@router.post("/start")
async def start_scan(
    request: ScanStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    폴더 트리 스캔 시작

    - 비동기 백그라운드 태스크로 실행
    - 이미지 파일 재귀 검색 (jpg/png/gif/bmp/webp/heic/tiff)
    - DB에 파일 정보 저장
    """
    global scan_state

    if scan_state["is_running"]:
        raise HTTPException(status_code=409, detail="스캔이 이미 실행 중입니다.")

    # 스캔 대상 폴더 결정
    root_folders = request.root_folders or settings.SCAN_ROOT_FOLDERS
    if not root_folders:
        raise HTTPException(
            status_code=400,
            detail="스캔 대상 폴더가 설정되지 않았습니다. SCAN_ROOT_FOLDERS를 설정하거나 root_folders를 전달하세요."
        )

    # 스캔 상태 초기화
    scan_state.update({
        "is_running": True,
        "total_folders": 0,
        "scanned_folders": 0,
        "total_files": 0,
        "scanned_files": 0,
        "current_folder": None,
        "error": None,
    })

    # 백그라운드에서 스캔 실행 (세션 전달하지 않음)
    background_tasks.add_task(run_scan_task, root_folders)

    return {
        "status": "started",
        "root_folders": root_folders,
        "message": "스캔이 시작되었습니다."
    }


@router.get("/status", response_model=ScanStatusResponse)
async def get_scan_status():
    """스캔 진행 상태 조회"""
    global scan_state

    progress = 0.0
    if scan_state["total_files"] > 0:
        progress = (scan_state["scanned_files"] / scan_state["total_files"]) * 100

    return ScanStatusResponse(
        is_running=scan_state["is_running"],
        total_folders=scan_state["total_folders"],
        scanned_folders=scan_state["scanned_folders"],
        total_files=scan_state["total_files"],
        scanned_files=scan_state["scanned_files"],
        progress_percent=round(progress, 2),
        current_folder=scan_state["current_folder"],
        error=scan_state["error"],
    )


@router.get("/folders")
async def get_folders(
    skip: int = 0,
    limit: int = 100,
    folder_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    폴더 목록 조회

    - 페이지네이션 지원
    - folder_status 필터링 (clear/unclear/flat/nested)
    """
    from sqlalchemy import text

    # 기본 쿼리
    query = "SELECT * FROM folder_mappings WHERE 1=1"
    params = {}

    # 필터 조건
    if folder_status:
        query += " AND folder_status = :folder_status"
        params["folder_status"] = folder_status

    # 정렬 및 페이지네이션
    query += " ORDER BY folder_path LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

    result = db.execute(text(query), params).fetchall()

    # 딕셔너리로 변환
    folders = []
    for row in result:
        folders.append({
            "id": row.id,
            "folder_path": row.folder_path,
            "file_count": row.file_count or 0,
            "folder_status": row.folder_status or "unknown",
            "category_id": row.category_id,
            "is_mixed": row.is_mixed or False,
        })

    return {
        "folders": folders,
        "skip": skip,
        "limit": limit,
        "total": len(folders),
    }


# === 백그라운드 태스크 ===
async def run_scan_task(root_folders: list[str]):
    """
    스캔 백그라운드 태스크

    - FolderScanner를 사용하여 재귀 스캔
    - 진행 상태를 scan_state에 업데이트
    """
    global scan_state

    # 백그라운드 태스크용 독립 세션 생성
    from ..database import SessionLocal
    db = SessionLocal()

    try:
        scanner = FolderScanner(db, settings)

        # 스캔 실행
        await scanner.scan_folders(root_folders, on_progress=update_scan_progress)

        scan_state["is_running"] = False
        print(f"[스캔 완료] 폴더: {scan_state['total_folders']}, 파일: {scan_state['total_files']}")

    except Exception as e:
        scan_state["error"] = str(e)
        scan_state["is_running"] = False
        print(f"[스캔 오류] {e}")
    finally:
        db.close()


def update_scan_progress(
    total_folders: int,
    scanned_folders: int,
    total_files: int,
    scanned_files: int,
    current_folder: str,
):
    """스캔 진행 상태 업데이트 콜백"""
    global scan_state
    scan_state.update({
        "total_folders": total_folders,
        "scanned_folders": scanned_folders,
        "total_files": total_files,
        "scanned_files": scanned_files,
        "current_folder": current_folder,
    })
