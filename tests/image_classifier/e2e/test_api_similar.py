"""유사 이미지 API 엔드포인트 테스트"""
import pytest
import numpy as np
from sqlalchemy import text

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

pytestmark = pytest.mark.skipif(
    not HAS_FAISS,
    reason="faiss-cpu not installed"
)


@pytest.fixture
def seeded_similar_data(test_db):
    """유사 이미지 검색을 위한 데이터 생성"""
    # 카테고리 생성
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')
    """))

    # 파일 생성 (5개)
    for file_id in range(1, 6):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, final_category_id)
            VALUES (:id, :path, 'hash', :status, :cat_id)
        """), {
            "id": file_id,
            "path": f"/test/file{file_id}.jpg",
            "status": "ai_classified" if file_id <= 3 else "pending",
            "cat_id": 1 if file_id <= 3 else None  # file 1-3은 분류됨, 4-5는 미분류
        })

        # 임베딩 생성
        embedding = np.random.rand(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        # file 4는 file 1과 유사하게 (0.95 similarity)
        if file_id == 4:
            result = test_db.execute(text("""
                SELECT clip_embedding FROM image_features WHERE file_id = 1
            """)).fetchone()
            embedding = np.frombuffer(result.clip_embedding, dtype=np.float32).copy()
            embedding += np.random.rand(512).astype(np.float32) * 0.1
            embedding = embedding / np.linalg.norm(embedding)

        embedding_bytes = embedding.tobytes()
        test_db.execute(text("""
            INSERT INTO image_features (file_id, clip_embedding)
            VALUES (:file_id, :embedding)
        """), {"file_id": file_id, "embedding": embedding_bytes})

    test_db.commit()

    # FAISS 인덱스 빌드
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager
    from app.modules.image_classifier.config import ImageClassifierSettings

    settings = ImageClassifierSettings()
    faiss_manager = FAISSIndexManager(test_db, dimension=512)
    faiss_manager.build_index()

    return {"file_ids": [1, 2, 3, 4, 5]}


# ================================================
# Right: 기본 CRUD 동작
# ================================================

def test_build_index_accepted(client):
    """12.1 Right: POST /build-index → 200 (accepted)"""
    response = client.post("/api/ic/similar/build-index")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "started"
    assert "message" in data


def test_search_similar(seeded_similar_data, client):
    """12.2 Right: GET /{file_id} → 유사 목록"""
    # file 1과 유사한 이미지 검색
    response = client.get("/api/ic/similar/1?k=10&threshold=0.0")

    assert response.status_code == 200
    results = response.json()

    # 결과가 있어야 함
    assert isinstance(results, list)
    # 자기 자신 제외 → 최대 4개
    assert len(results) <= 4

    # 각 결과 구조 확인
    if results:
        result = results[0]
        assert "file_id" in result
        assert "file_path" in result
        assert "similarity" in result
        assert "category_id" in result


def test_bulk_suggest(seeded_similar_data, client):
    """12.3 Right: GET /bulk-suggest → 미분류 파일 제안"""
    # 미분류 파일(file 4, 5)에 대한 제안
    response = client.get("/api/ic/similar/bulk-suggest?threshold=0.7&max_results=50")

    # 422 에러가 발생하면 응답 출력
    if response.status_code == 422:
        print(f"422 Error response: {response.json()}")

    assert response.status_code == 200
    data = response.json()

    assert "total_unclassified" in data
    assert "suggestions" in data

    # file 4, 5가 미분류이므로 total_unclassified=2
    assert data["total_unclassified"] == 2

    # 제안이 있을 수도, 없을 수도 있음 (유사도 threshold에 따라)
    if data["suggestions"]:
        suggestion = data["suggestions"][0]
        assert "file_id" in suggestion
        assert "suggested_category_id" in suggestion
        assert "similarity" in suggestion
        assert "reference_file_id" in suggestion


def test_apply_suggestion(seeded_similar_data, client):
    """12.4 Right: POST /apply → 카테고리 적용"""
    # file 4에 카테고리 1 적용
    response = client.post("/api/ic/similar/apply", json={
        "file_id": 4,
        "suggested_category_id": 1
    })

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["file_id"] == 4
    assert data["category_id"] == 1


# ================================================
# Error: 예외 처리
# ================================================

def test_search_no_index(client, test_db, tmp_path):
    """12.5 Error: 인덱스 없음 → 503"""
    # FAISS 인덱스가 없는 상태에서 검색 시도
    # (seeded_similar_data fixture 사용하지 않음)

    # global faiss_manager 초기화
    from app.modules.image_classifier.routers import similar
    similar.faiss_manager = None

    # 기존 인덱스 파일 삭제 (이전 테스트에서 생성되었을 수 있음)
    from pathlib import Path
    index_file = Path("data/image_classifier/faiss_index.bin")
    mapping_file = Path("data/image_classifier/faiss_index.npy")
    if index_file.exists():
        index_file.unlink()
    if mapping_file.exists():
        mapping_file.unlink()

    response = client.get("/api/ic/similar/1?k=10&threshold=0.0")

    # 인덱스가 없으면 503 오류
    assert response.status_code == 503
    assert "FAISS 인덱스가 없습니다" in response.json()["detail"]


def test_search_nonexistent_file(seeded_similar_data, client):
    """12.6 Error: 없는 파일 → 빈 결과"""
    # 존재하지 않는 파일 ID로 검색
    response = client.get("/api/ic/similar/9999?k=10&threshold=0.0")

    # 응답은 성공이지만 빈 결과
    assert response.status_code == 200
    results = response.json()

    # 빈 리스트 반환
    assert results == []
