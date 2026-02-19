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
    resume: bool = False  # True면 이미 스캔된 폴더 스킵


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

# 스캔 취소 이벤트
cancel_event = asyncio.Event()


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
    cancel_event.clear()
    scan_state.update({
        "is_running": True,
        "total_folders": 0,
        "scanned_folders": 0,
        "total_files": 0,
        "scanned_files": 0,
        "current_folder": None,
        "error": None,
    })

    # 백그라운드에서 스캔 실행
    background_tasks.add_task(run_scan_task, root_folders, request.resume)

    return {
        "status": "started",
        "root_folders": root_folders,
        "resume": request.resume,
        "message": "스캔이 시작되었습니다." if not request.resume else "이어서 스캔을 시작합니다."
    }


@router.post("/stop")
async def stop_scan(db: Session = Depends(get_db)):
    """
    스캔 중지

    - 실행 중인 스캔을 일시 중지
    - DB에 진행 상태 저장 (resume으로 이어서 가능)
    """
    global scan_state

    if not scan_state["is_running"]:
        raise HTTPException(status_code=400, detail="실행 중인 스캔이 없습니다.")

    cancel_event.set()

    # task_progress DB 업데이트
    task_id = scan_state.get("task_id")
    if task_id:
        from ..workers.task_progress import TaskProgressManager
        progress_mgr = TaskProgressManager(db)
        progress_mgr.pause_task(task_id)

    return {
        "status": "stopping",
        "message": "스캔 중지 요청이 전송되었습니다.",
        "scanned_folders": scan_state["scanned_folders"],
    }


@router.get("/status", response_model=ScanStatusResponse)
async def get_scan_status(db: Session = Depends(get_db)):
    """스캔 진행 상태 조회 — DB 우선, 메모리 fallback"""
    global scan_state

    # 메모리에서 실행 중이면 메모리 데이터 사용 (실시간성 우선)
    if scan_state["is_running"]:
        progress = 0.0
        if scan_state["total_files"] > 0:
            progress = (scan_state["scanned_files"] / scan_state["total_files"]) * 100
        return ScanStatusResponse(
            is_running=True,
            total_folders=scan_state["total_folders"],
            scanned_folders=scan_state["scanned_folders"],
            total_files=scan_state["total_files"],
            scanned_files=scan_state["scanned_files"],
            progress_percent=round(progress, 2),
            current_folder=scan_state["current_folder"],
            error=scan_state["error"],
        )

    # 메모리에 없으면 DB에서 최신 작업 조회 (서버 재시작 후)
    from ..workers.task_progress import TaskProgressManager
    progress_mgr = TaskProgressManager(db)
    latest = progress_mgr.get_latest('scan')

    if latest:
        total = latest["total_items"] or 0
        processed = latest["processed_items"] or 0
        progress = (processed / total * 100) if total > 0 else 0.0
        return ScanStatusResponse(
            is_running=latest["status"] == "running",
            total_folders=total,
            scanned_folders=processed,
            total_files=0,
            scanned_files=0,
            progress_percent=round(progress, 2),
            current_folder=latest["current_item"],
            error=latest["error_message"],
        )

    # DB에도 없으면 기본값
    return ScanStatusResponse(
        is_running=False,
        total_folders=0,
        scanned_folders=0,
        total_files=0,
        scanned_files=0,
        progress_percent=0.0,
        current_folder=None,
        error=None,
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

    # 필터 조건
    where_clause = "WHERE 1=1"
    params = {}
    if folder_status:
        where_clause += " AND folder_status = :folder_status"
        params["folder_status"] = folder_status

    # total 카운트 (전체 개수)
    count_query = f"SELECT COUNT(*) FROM folder_mappings {where_clause}"
    total = db.execute(text(count_query), params).scalar() or 0

    # 데이터 쿼리
    query = f"SELECT * FROM folder_mappings {where_clause} ORDER BY folder_path LIMIT :limit OFFSET :skip"
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
        "total": total,
        "has_more": skip + limit < total,
    }


# === 백그라운드 태스크 ===
async def run_scan_task(root_folders: list[str], resume: bool = False):
    """
    스캔 백그라운드 태스크

    - FolderScanner를 사용하여 재귀 스캔
    - 진행 상태를 scan_state + DB(task_progress)에 업데이트
    - cancel_event 감시하여 중지 지원
    - resume=True 시 이미 스캔된 폴더의 파일 스캔 스킵
    """
    global scan_state

    from pathlib import Path
    from ..database import SessionLocal
    from ..workers.task_progress import TaskProgressManager
    from sqlalchemy import text as sa_text

    db = SessionLocal()
    progress_mgr = TaskProgressManager(db)
    task_id = None

    try:
        scanner = FolderScanner(db, settings)

        # 폴더 트리 먼저 수집하여 total 파악
        all_folders = []
        for root in root_folders:
            root_path = Path(root)
            if root_path.exists():
                all_folders.extend(scanner._collect_folders(root_path))

        # resume 모드: 이미 스캔된 폴더 목록 조회
        scanned_paths = set()
        if resume:
            rows = db.execute(sa_text("SELECT folder_path FROM folder_mappings")).fetchall()
            scanned_paths = {row.folder_path for row in rows}

        total = len(all_folders)
        task_id = progress_mgr.start_task('scan', total)
        scan_state["task_id"] = task_id

        # 직접 폴더별 스캔 (cancel_event 체크 포함)
        scanned_count = 0
        for folder_path in all_folders:
            # 취소 확인
            if cancel_event.is_set():
                print(f"[스캔 중지] {scanned_count}/{total} 폴더 완료 시점에서 중지됨")
                scan_state["is_running"] = False
                progress_mgr.pause_task(task_id)
                return

            # resume 모드: 이미 스캔된 폴더의 파일은 스킵
            if resume and str(folder_path) in scanned_paths:
                scanned_count += 1
                continue

            await scanner._scan_folder_files(folder_path)
            scanned_count += 1
            scanner.scanned_folders = scanned_count
            scanner.total_folders = total

            # 진행 상태 업데이트
            update_scan_progress(total, scanned_count, scanner.total_files, scanner.scanned_files, str(folder_path))
            try:
                progress_mgr.update_progress(task_id, scanned_count, str(folder_path))
            except Exception:
                pass

        scan_state["is_running"] = False
        progress_mgr.complete_task(task_id)
        print(f"[스캔 완료] 폴더: {scanned_count}/{total}, 파일: {scanner.total_files}")

    except Exception as e:
        scan_state["error"] = str(e)
        scan_state["is_running"] = False
        if task_id:
            progress_mgr.fail_task(task_id, str(e))
        print(f"[스캔 오류] {e}")
    finally:
        db.close()


@router.get("/history")
async def get_scan_history(db: Session = Depends(get_db)):
    """스캔 작업 이력 조회 (최근 10건)"""
    from ..workers.task_progress import TaskProgressManager
    progress_mgr = TaskProgressManager(db)
    return {"history": progress_mgr.get_history('scan', limit=10)}


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
