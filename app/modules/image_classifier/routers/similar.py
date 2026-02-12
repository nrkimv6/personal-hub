"""
유사 이미지 검색 관련 API 엔드포인트

- GET /api/ic/similar/{file_id}: 특정 파일과 유사한 이미지 검색
- GET /api/ic/similar/bulk-suggest: 벌크 유사 분류 제안
- POST /api/ic/similar/apply: 유사 분류 적용
- POST /api/ic/similar/build-index: FAISS 인덱스 빌드
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..workers.faiss_index import FAISSIndexManager

router = APIRouter(prefix="/similar", tags=["Similar"])


# === 요청/응답 스키마 ===
class SimilarImageResponse(BaseModel):
    """유사 이미지 응답"""
    file_id: int
    file_path: str
    similarity: float
    category_id: Optional[int]
    category_path: Optional[str]


class BulkSuggestRequest(BaseModel):
    """벌크 유사 제안 요청"""
    threshold: float = 0.85
    max_results: int = 50


class ApplySimilarRequest(BaseModel):
    """유사 분류 적용 요청"""
    file_id: int
    suggested_category_id: int


# === 전역 상태 ===
faiss_manager: Optional[FAISSIndexManager] = None


# === 엔드포인트 ===
@router.post("/build-index")
async def build_faiss_index(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    FAISS 인덱스 빌드 (백그라운드)

    - 모든 CLIP 임베딩으로 인덱스 생성
    - 시간 소요: ~5분 (30만 개 벡터)
    """
    global faiss_manager

    # 백그라운드 태스크로 실행
    background_tasks.add_task(_build_index_task, db)

    return {
        "status": "started",
        "message": "FAISS 인덱스 빌드가 시작되었습니다. 완료까지 수 분 소요됩니다."
    }


@router.get("/{file_id}", response_model=list[SimilarImageResponse])
async def get_similar_images(
    file_id: int,
    k: int = 10,
    threshold: float = 0.7,
    db: Session = Depends(get_db)
):
    """
    특정 파일과 유사한 이미지 검색

    Args:
        file_id: 기준 파일 ID
        k: 반환할 결과 수
        threshold: 유사도 임계값 (0~1)
    """
    global faiss_manager

    # FAISS 매니저 초기화
    if faiss_manager is None:
        faiss_manager = FAISSIndexManager(db)
        if not faiss_manager.load_index():
            raise HTTPException(
                status_code=503,
                detail="FAISS 인덱스가 없습니다. 먼저 /api/ic/similar/build-index를 호출하세요."
            )

    # 유사 이미지 검색
    similar_files = faiss_manager.search_similar(file_id, k, threshold)

    # 결과 조회
    results = []
    for similar_file_id, similarity in similar_files:
        query = text("""
            SELECT fc.file_path, fc.final_category_id, cat.full_path
            FROM file_classifications fc
            LEFT JOIN categories cat ON fc.final_category_id = cat.id
            WHERE fc.id = :file_id
        """)
        file_info = db.execute(query, {"file_id": similar_file_id}).fetchone()

        if file_info:
            results.append(SimilarImageResponse(
                file_id=similar_file_id,
                file_path=file_info.file_path,
                similarity=similarity,
                category_id=file_info.final_category_id,
                category_path=file_info.full_path,
            ))

    return results


@router.get("/bulk-suggest")
async def bulk_suggest_similar(
    threshold: float = 0.85,
    max_results: int = 50,
    db: Session = Depends(get_db)
):
    """
    벌크 유사 분류 제안

    - 분류된 파일 기준으로 미분류 파일 유사도 검색
    - threshold 이상이면 자동 제안
    """
    global faiss_manager

    # FAISS 매니저 초기화
    if faiss_manager is None:
        faiss_manager = FAISSIndexManager(db)
        if not faiss_manager.load_index():
            raise HTTPException(
                status_code=503,
                detail="FAISS 인덱스가 없습니다."
            )

    # 미분류 파일 조회
    unclassified_query = text("""
        SELECT fc.id, feat.clip_embedding
        FROM file_classifications fc
        INNER JOIN image_features feat ON fc.id = feat.file_id
        WHERE fc.final_category_id IS NULL
        AND feat.clip_embedding IS NOT NULL
        LIMIT :max_results
    """)
    unclassified_files = db.execute(unclassified_query, {"max_results": max_results}).fetchall()

    # 각 미분류 파일에 대해 유사 파일 검색
    suggestions = []
    import numpy as np

    for file in unclassified_files:
        file_id = file.id
        embedding = np.frombuffer(file.clip_embedding, dtype=np.float32)

        # 유사 파일 검색 (분류된 파일만)
        similar_results = faiss_manager.search_by_embedding(embedding, k=5, threshold=threshold)

        if not similar_results:
            continue

        # 가장 유사한 파일의 카테고리 조회
        similar_file_id = similar_results[0][0]
        similarity = similar_results[0][1]

        category_query = text("""
            SELECT final_category_id, fc.file_path, cat.full_path
            FROM file_classifications fc
            LEFT JOIN categories cat ON fc.final_category_id = cat.id
            WHERE fc.id = :file_id
            AND fc.final_category_id IS NOT NULL
        """)
        category_info = db.execute(category_query, {"file_id": similar_file_id}).fetchone()

        if category_info and category_info.final_category_id:
            # 미분류 파일 정보 조회
            unclassified_query = text("SELECT file_path FROM file_classifications WHERE id = :file_id")
            unclassified_info = db.execute(unclassified_query, {"file_id": file_id}).fetchone()

            suggestions.append({
                "file_id": file_id,
                "file_path": unclassified_info.file_path if unclassified_info else None,
                "suggested_category_id": category_info.final_category_id,
                "suggested_category_path": category_info.full_path,
                "similarity": similarity,
                "reference_file_id": similar_file_id,
                "reference_file_path": category_info.file_path,
            })

    return {
        "total_unclassified": len(unclassified_files),
        "suggestions": suggestions,
    }


@router.post("/apply")
async def apply_similar_classification(
    request: ApplySimilarRequest,
    db: Session = Depends(get_db)
):
    """
    유사 분류 적용

    - 제안된 카테고리를 파일에 할당
    """
    # 카테고리 존재 확인
    cat_query = text("SELECT id FROM categories WHERE id = :cat_id")
    category = db.execute(cat_query, {"cat_id": request.suggested_category_id}).fetchone()

    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다.")

    # 파일 업데이트
    update_query = text("""
        UPDATE file_classifications
        SET final_category_id = :cat_id,
            status = 'ai_classified'
        WHERE id = :file_id
    """)
    db.execute(update_query, {"cat_id": request.suggested_category_id, "file_id": request.file_id})
    db.commit()

    return {
        "status": "success",
        "file_id": request.file_id,
        "category_id": request.suggested_category_id,
        "message": "유사 분류 적용 완료"
    }


# === 백그라운드 태스크 ===
async def _build_index_task(db: Session):
    """FAISS 인덱스 빌드 백그라운드 태스크"""
    global faiss_manager

    try:
        faiss_manager = FAISSIndexManager(db)
        stats = faiss_manager.build_index()
        print(f"[FAISS 인덱스 빌드 완료] {stats}")
    except Exception as e:
        print(f"[FAISS 인덱스 빌드 오류] {e}")
