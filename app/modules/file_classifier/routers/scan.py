"""
파일 스캔 API 엔드포인트

- POST /scan/start: 폴더 스캔 시작 (BackgroundTasks)
- POST /scan/stop: 스캔 중지
- GET /scan/status: 스캔 진행 상태 조회 (폴링)
"""

import threading
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..workers.scanner import FileScanner
from ..workers.metadata_extractor import MetadataExtractor
from ..workers.pipeline import PipelineWorker
from ..workers.task_progress import TaskProgressManager
from ..config import settings

router = APIRouter(tags=["File Classifier - Scan"])


# === 요청/응답 스키마 ===
class ScanStartRequest(BaseModel):
    root_folders: Optional[list[str]] = None  # None이면 config의 SCAN_ROOT_FOLDERS 사용


class ScanStatusResponse(BaseModel):
    is_running: bool
    total_files: int
    processed_files: int
    progress_percent: float
    current_file: Optional[str]
    error: Optional[str]
    task_id: Optional[int]


# === 전역 스캔 상태 (스레드 안전) ===
scan_state = {
    "is_running": False,
    "total_files": 0,
    "processed_files": 0,
    "current_file": None,
    "error": None,
    "task_id": None,
}

_scan_lock = threading.Lock()
_scanner_instance: Optional[FileScanner] = None


def _run_scan_background(root_folders: list[str]):
    """백그라운드 스캔 실행 (별도 스레드)"""
    global _scanner_instance

    db = SessionLocal()
    try:
        progress_mgr = TaskProgressManager(db)
        task_id = progress_mgr.start_task("scan", 0)

        with _scan_lock:
            scan_state["is_running"] = True
            scan_state["task_id"] = task_id
            scan_state["error"] = None
            scan_state["processed_files"] = 0
            scan_state["total_files"] = 0
            scan_state["current_file"] = None

        scanner = FileScanner(db)
        _scanner_instance = scanner

        def on_progress(processed: int, total: int, current: str):
            with _scan_lock:
                scan_state["processed_files"] = processed
                scan_state["total_files"] = total
                scan_state["current_file"] = current

        stats = scanner.scan(root_folders, task_id=task_id, progress_callback=on_progress)
        progress_mgr.complete_task(task_id)

        with _scan_lock:
            scan_state["is_running"] = False
            scan_state["total_files"] = stats["total"]
            scan_state["processed_files"] = stats["inserted"]

    except Exception as e:
        with _scan_lock:
            scan_state["is_running"] = False
            scan_state["error"] = str(e)
        if scan_state.get("task_id"):
            try:
                TaskProgressManager(db).fail_task(scan_state["task_id"], str(e))
            except Exception:
                pass
    finally:
        _scanner_instance = None
        db.close()


@router.post("/scan/start")
async def scan_start(
    request: ScanStartRequest,
    background_tasks: BackgroundTasks,
):
    """파일 스캔 시작"""
    if scan_state["is_running"]:
        return {"status": "already_running", "message": "스캔이 이미 진행 중입니다"}

    root_folders = request.root_folders or settings.SCAN_ROOT_FOLDERS
    if not root_folders:
        return {"status": "error", "message": "스캔할 폴더가 지정되지 않았습니다. settings.SCAN_ROOT_FOLDERS를 설정하세요"}

    background_tasks.add_task(_run_scan_background, root_folders)
    return {"status": "started", "root_folders": root_folders}


@router.post("/scan/stop")
async def scan_stop():
    """스캔 중지"""
    global _scanner_instance
    if not scan_state["is_running"]:
        return {"status": "not_running"}

    if _scanner_instance:
        _scanner_instance.stop()

    return {"status": "stop_requested"}


@router.get("/scan/status", response_model=ScanStatusResponse)
async def scan_status():
    """스캔 진행 상태 조회"""
    with _scan_lock:
        total = scan_state["total_files"]
        processed = scan_state["processed_files"]
        pct = round(processed / total * 100, 1) if total > 0 else 0.0

        return ScanStatusResponse(
            is_running=scan_state["is_running"],
            total_files=total,
            processed_files=processed,
            progress_percent=pct,
            current_file=scan_state["current_file"],
            error=scan_state["error"],
            task_id=scan_state["task_id"],
        )


# === 메타데이터 추출 상태 ===
metadata_state = {
    "is_running": False,
    "total": 0,
    "processed": 0,
    "error": None,
}
_metadata_lock = threading.Lock()
_metadata_extractor: Optional[MetadataExtractor] = None


def _run_metadata_background():
    global _metadata_extractor
    db = SessionLocal()
    try:
        with _metadata_lock:
            metadata_state["is_running"] = True
            metadata_state["error"] = None
            metadata_state["processed"] = 0

        extractor = MetadataExtractor(db)
        _metadata_extractor = extractor
        stats = extractor.extract()

        with _metadata_lock:
            metadata_state["is_running"] = False
            metadata_state["total"] = stats["total"]
            metadata_state["processed"] = stats["processed"]
    except Exception as e:
        with _metadata_lock:
            metadata_state["is_running"] = False
            metadata_state["error"] = str(e)
    finally:
        _metadata_extractor = None
        db.close()


@router.post("/scan/metadata/start")
async def metadata_start(background_tasks: BackgroundTasks):
    """메타데이터 추출 시작"""
    with _metadata_lock:
        if metadata_state["is_running"]:
            return {"status": "already_running"}
    background_tasks.add_task(_run_metadata_background)
    return {"status": "started"}


@router.get("/scan/metadata/status")
async def metadata_status():
    """메타데이터 추출 상태 조회"""
    with _metadata_lock:
        return {
            "is_running": metadata_state["is_running"],
            "total": metadata_state["total"],
            "processed": metadata_state["processed"],
            "error": metadata_state["error"],
        }


# === 파이프라인 상태 ===
pipeline_state = {
    "is_running": False,
    "current_stage": None,
    "results": {},
    "error": None,
}
_pipeline_lock = threading.Lock()
_pipeline_worker: Optional[PipelineWorker] = None


def _run_pipeline_background(root_folders):
    global _pipeline_worker
    db = SessionLocal()
    try:
        with _pipeline_lock:
            pipeline_state["is_running"] = True
            pipeline_state["error"] = None
            pipeline_state["results"] = {}
            pipeline_state["current_stage"] = None

        worker = PipelineWorker(db)
        _pipeline_worker = worker

        def on_progress(stage, processed, total):
            with _pipeline_lock:
                pipeline_state["current_stage"] = stage

        results = worker.run(root_folders, progress_callback=on_progress)

        with _pipeline_lock:
            pipeline_state["is_running"] = False
            pipeline_state["results"] = results
            pipeline_state["current_stage"] = "done"
    except Exception as e:
        with _pipeline_lock:
            pipeline_state["is_running"] = False
            pipeline_state["error"] = str(e)
    finally:
        _pipeline_worker = None
        db.close()


class PipelineStartRequest(BaseModel):
    root_folders: Optional[list[str]] = None


@router.post("/pipeline/start")
async def pipeline_start(request: PipelineStartRequest, background_tasks: BackgroundTasks):
    """파이프라인 전체 실행 시작"""
    with _pipeline_lock:
        if pipeline_state["is_running"]:
            return {"status": "already_running"}
    root_folders = request.root_folders or settings.SCAN_ROOT_FOLDERS
    background_tasks.add_task(_run_pipeline_background, root_folders)
    return {"status": "started"}


@router.post("/pipeline/stop")
async def pipeline_stop():
    """파이프라인 중지"""
    global _pipeline_worker
    if not pipeline_state["is_running"]:
        return {"status": "not_running"}
    if _pipeline_worker:
        _pipeline_worker.stop()
    return {"status": "stop_requested"}


@router.get("/pipeline/status")
async def pipeline_status():
    """파이프라인 상태 조회"""
    with _pipeline_lock:
        return {
            "is_running": pipeline_state["is_running"],
            "current_stage": pipeline_state["current_stage"],
            "results": pipeline_state["results"],
            "error": pipeline_state["error"],
        }
