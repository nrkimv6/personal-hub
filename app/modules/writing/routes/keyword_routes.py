"""Keyword API Routes - 키워드 분석 및 관리 API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.writing.services.keyword_analyzer import KeywordAnalyzer
from app.modules.writing.services.keyword_service import KeywordService

router = APIRouter(prefix="/api/writing/keywords", tags=["keywords"])


# ========== Pydantic 스키마 ==========


class PromoteRequest(BaseModel):
    """키워드 승격 요청."""

    keyword_id: int
    season_hint: Optional[str] = None


class BatchPromoteRequest(BaseModel):
    """일괄 승격 요청."""

    limit: int = 50
    min_frequency: int = 100
    season_hint: Optional[str] = None


class StopwordCreateRequest(BaseModel):
    """불용어 추가 요청."""

    word: str
    category: str = "general"


class AnalyzeRequest(BaseModel):
    """분석 실행 요청."""

    mode: str = "incremental"  # 'full' or 'incremental'
    min_freq: int = 3
    min_length: int = 2


# ========== 키워드 조회 ==========


@router.get("")
def list_keywords(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    min_frequency: int = Query(0, ge=0),
    include_stopwords: bool = False,
    include_promoted: bool = True,
    db: Session = Depends(get_db),
):
    """키워드 목록 조회."""
    service = KeywordService(db)
    keywords = service.get_keywords(
        limit=limit,
        offset=offset,
        min_frequency=min_frequency,
        include_stopwords=include_stopwords,
        include_promoted=include_promoted,
    )

    return {
        "items": [_keyword_to_dict(k) for k in keywords],
        "count": len(keywords),
        "offset": offset,
        "limit": limit,
    }


@router.get("/candidates")
def list_candidates(
    limit: int = Query(50, ge=1, le=200),
    min_frequency: int = Query(100, ge=1),
    db: Session = Depends(get_db),
):
    """승격 후보 키워드 조회 (미검토 + 고빈도)."""
    service = KeywordService(db)
    candidates = service.get_candidates(limit=limit, min_frequency=min_frequency)

    return {
        "items": [_keyword_to_dict(k) for k in candidates],
        "count": len(candidates),
    }


@router.get("/stats")
def get_keyword_stats(db: Session = Depends(get_db)):
    """키워드 통계 요약."""
    service = KeywordService(db)
    return service.get_stats()


# ========== 키워드 승격 ==========


@router.post("/promote")
def promote_keyword(
    data: PromoteRequest,
    db: Session = Depends(get_db),
):
    """키워드를 writing_elements로 승격."""
    service = KeywordService(db)
    try:
        element = service.promote_to_element(
            keyword_id=data.keyword_id,
            season_hint=data.season_hint,
        )
        return {
            "success": True,
            "element": {
                "id": element.id,
                "name": element.name,
                "category": element.category,
                "frequency": element.frequency,
            },
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/promote-batch")
def promote_batch(
    data: BatchPromoteRequest,
    db: Session = Depends(get_db),
):
    """상위 N개 키워드 일괄 승격."""
    service = KeywordService(db)
    elements = service.promote_batch(
        limit=data.limit,
        min_frequency=data.min_frequency,
        season_hint=data.season_hint,
    )

    return {
        "success": True,
        "promoted_count": len(elements),
        "elements": [
            {
                "id": e.id,
                "name": e.name,
                "frequency": e.frequency,
            }
            for e in elements
        ],
    }


# ========== 불용어 관리 ==========


@router.post("/{keyword_id}/mark-stopword")
def mark_as_stopword(
    keyword_id: int,
    db: Session = Depends(get_db),
):
    """키워드를 불용어로 마킹."""
    service = KeywordService(db)
    try:
        kw = service.mark_as_stopword(keyword_id)
        return {"success": True, "keyword": kw.keyword}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/stopwords")
def list_stopwords(db: Session = Depends(get_db)):
    """불용어 목록 조회."""
    service = KeywordService(db)
    stopwords = service.get_stopwords()

    return {
        "items": [
            {
                "id": s.id,
                "word": s.word,
                "category": s.category,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in stopwords
        ],
        "count": len(stopwords),
    }


@router.post("/stopwords")
def add_stopword(
    data: StopwordCreateRequest,
    db: Session = Depends(get_db),
):
    """불용어 추가."""
    service = KeywordService(db)
    try:
        stopword = service.add_stopword(word=data.word, category=data.category)
        return {
            "success": True,
            "stopword": {
                "id": stopword.id,
                "word": stopword.word,
                "category": stopword.category,
            },
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/stopwords/{stopword_id}")
def remove_stopword(
    stopword_id: int,
    db: Session = Depends(get_db),
):
    """불용어 삭제."""
    service = KeywordService(db)
    success = service.remove_stopword(stopword_id)
    if not success:
        raise HTTPException(404, "Stopword not found")
    return {"deleted": True}


# ========== 분석 실행 ==========


@router.post("/analyze")
def run_analysis(
    data: AnalyzeRequest,
    db: Session = Depends(get_db),
):
    """키워드 분석 실행."""
    analyzer = KeywordAnalyzer(db)

    try:
        if data.mode == "full":
            result = analyzer.analyze_all(
                min_freq=data.min_freq,
                min_length=data.min_length,
            )
        else:
            result = analyzer.analyze_incremental(
                min_freq=data.min_freq,
                min_length=data.min_length,
            )

        return {"success": True, "mode": data.mode, **result}
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {e}")


# ========== 헬퍼 함수 ==========


def _keyword_to_dict(keyword) -> dict:
    """KeywordStats를 dict로 변환."""
    return {
        "id": keyword.id,
        "keyword": keyword.keyword,
        "frequency": keyword.frequency,
        "source_count": keyword.source_count,
        "avg_per_source": keyword.avg_per_source,
        "is_stopword": bool(keyword.is_stopword),
        "is_promoted": bool(keyword.is_promoted),
        "element_id": keyword.element_id,
        "reviewed_at": keyword.reviewed_at.isoformat() if keyword.reviewed_at else None,
        "analyzed_at": keyword.analyzed_at.isoformat() if keyword.analyzed_at else None,
    }
