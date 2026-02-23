"""분류 API 엔드포인트"""
import threading
from typing import Optional, List
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text

from ..database import SessionLocal
from ..workers.rule_classifier import RuleClassifier
from ..workers.llm_classifier import LLMClassifier

router = APIRouter(tags=["File Classifier - Classify"])

# === 전역 분류 상태 ===
classify_state = {
    "is_running": False,
    "total": 0,
    "classified": 0,
    "unclassified": 0,
    "error": None,
}
_classify_lock = threading.Lock()
_classifier_instance: Optional[RuleClassifier] = None

llm_state = {
    "is_running": False,
    "total": 0,
    "classified": 0,
    "errors": 0,
    "error": None,
}
_llm_lock = threading.Lock()
_llm_instance: Optional[LLMClassifier] = None


def _run_rule_classify_background():
    global _classifier_instance
    db = SessionLocal()
    try:
        with _classify_lock:
            classify_state["is_running"] = True
            classify_state["error"] = None

        classifier = RuleClassifier(db)
        _classifier_instance = classifier
        stats = classifier.classify()

        with _classify_lock:
            classify_state["is_running"] = False
            classify_state.update(stats)
    except Exception as e:
        with _classify_lock:
            classify_state["is_running"] = False
            classify_state["error"] = str(e)
    finally:
        _classifier_instance = None
        db.close()


def _run_llm_classify_background():
    global _llm_instance
    db = SessionLocal()
    try:
        with _llm_lock:
            llm_state["is_running"] = True
            llm_state["error"] = None

        classifier = LLMClassifier(db)
        _llm_instance = classifier
        stats = classifier.classify()

        with _llm_lock:
            llm_state["is_running"] = False
            llm_state.update(stats)
    except Exception as e:
        with _llm_lock:
            llm_state["is_running"] = False
            llm_state["error"] = str(e)
    finally:
        _llm_instance = None
        db.close()


class ApproveRequest(BaseModel):
    file_ids: List[int]
    category_id: int


@router.post("/classify/rule/start")
async def classify_rule_start(background_tasks: BackgroundTasks):
    """규칙 기반 분류 시작"""
    if classify_state["is_running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_rule_classify_background)
    return {"status": "started"}


@router.get("/classify/status")
async def classify_status():
    """분류 상태 조회"""
    with _classify_lock:
        return dict(classify_state)


@router.post("/classify/approve")
async def classify_approve(request: ApproveRequest):
    """파일 승인 (최종 카테고리 설정)"""
    db = SessionLocal()
    try:
        for file_id in request.file_ids:
            db.execute(text(
                "UPDATE fc_files SET final_category_id = :cat_id, status = 'approved', "
                "classified_at = CURRENT_TIMESTAMP WHERE id = :id"
            ), {"cat_id": request.category_id, "id": file_id})
        db.commit()
        return {"status": "approved", "count": len(request.file_ids)}
    finally:
        db.close()


@router.post("/classify/llm/start")
async def classify_llm_start(background_tasks: BackgroundTasks):
    """LLM 분류 시작"""
    if llm_state["is_running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_llm_classify_background)
    return {"status": "started"}


@router.get("/classify/llm/status")
async def classify_llm_status():
    """LLM 분류 상태"""
    with _llm_lock:
        return dict(llm_state)
