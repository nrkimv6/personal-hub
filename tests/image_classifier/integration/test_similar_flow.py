"""유사분류 파이프라인 통합 테스트: CLIP 임베딩 → FAISS 인덱스 → bulk-suggest"""
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
def similar_pipeline_data(test_db):
    """유사분류 파이프라인 테스트 데이터 (CLIP 임베딩 포함)"""
    # 카테고리
    test_db.execute(text("INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')"))
    test_db.execute(text("INSERT INTO categories (id, name, full_path) VALUES (2, 'Food', 'Food')"))

    # 기준 임베딩 생성 (Travel 카테고리용)
    travel_embedding = np.random.rand(512).astype(np.float32)
    travel_embedding = travel_embedding / np.linalg.norm(travel_embedding)

    food_embedding = np.random.rand(512).astype(np.float32)
    food_embedding = food_embedding / np.linalg.norm(food_embedding)

    # 파일 1-2: Travel 분류됨 (임베딩: travel 기반)
    for file_id in [1, 2]:
        emb = travel_embedding.copy()
        emb += np.random.rand(512).astype(np.float32) * 0.01
        emb = emb / np.linalg.norm(emb)

        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status, final_category_id)
            VALUES (:id, :path, :hash, 'ai_classified', 1)
        """), {"id": file_id, "path": f"/test/travel{file_id}.jpg", "hash": f"hash{file_id}"})
        test_db.execute(text("""
            INSERT INTO image_features (file_id, clip_embedding)
            VALUES (:file_id, :embedding)
        """), {"file_id": file_id, "embedding": emb.tobytes()})

    # 파일 3: Food 분류됨
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status, final_category_id)
        VALUES (3, '/test/food1.jpg', 'hash3', 'ai_classified', 2)
    """))
    test_db.execute(text("""
        INSERT INTO image_features (file_id, clip_embedding)
        VALUES (3, :embedding)
    """), {"embedding": food_embedding.tobytes()})

    # 파일 4: 미분류, Travel과 유사한 임베딩
    similar_to_travel = travel_embedding.copy()
    similar_to_travel += np.random.rand(512).astype(np.float32) * 0.02
    similar_to_travel = similar_to_travel / np.linalg.norm(similar_to_travel)

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status)
        VALUES (4, '/test/unknown1.jpg', 'hash4', 'pending')
    """))
    test_db.execute(text("""
        INSERT INTO image_features (file_id, clip_embedding)
        VALUES (4, :embedding)
    """), {"embedding": similar_to_travel.tobytes()})

    # 파일 5: 미분류, 독립적인 임베딩 (어떤 것과도 유사하지 않음)
    random_embedding = np.random.rand(512).astype(np.float32)
    random_embedding = random_embedding / np.linalg.norm(random_embedding)

    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status)
        VALUES (5, '/test/unknown2.jpg', 'hash5', 'pending')
    """))
    test_db.execute(text("""
        INSERT INTO image_features (file_id, clip_embedding)
        VALUES (5, :embedding)
    """), {"embedding": random_embedding.tobytes()})

    test_db.commit()

    return {
        "travel_embedding": travel_embedding,
        "food_embedding": food_embedding,
    }


# ================================================
# Right: 파이프라인 정상 동작
# ================================================

def test_faiss_index_build_from_embeddings(test_db, similar_pipeline_data):
    """1.1 Right: CLIP 임베딩 → FAISS 인덱스 빌드 성공"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager

    manager = FAISSIndexManager(test_db, dimension=512)
    result = manager.build_index()

    assert result["total"] == 5
    assert result["indexed"] == 5


def test_search_finds_similar_travel(test_db, similar_pipeline_data):
    """1.2 Right: Travel 임베딩으로 검색 → Travel 파일 발견"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager

    manager = FAISSIndexManager(test_db, dimension=512)
    manager.build_index()

    # 파일 4 (Travel과 유사)로 검색
    results = manager.search_similar(file_id=4, k=5, threshold=0.7)

    assert len(results) > 0
    result_ids = [fid for fid, _ in results]
    # Travel 파일 (1 또는 2)이 결과에 포함
    assert 1 in result_ids or 2 in result_ids


def test_bulk_suggest_proposes_travel_category(test_db, similar_pipeline_data):
    """1.3 Right: bulk-suggest → 파일 4에 Travel 카테고리 제안"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager
    from app.modules.image_classifier.routers import similar

    manager = FAISSIndexManager(test_db, dimension=512)
    manager.build_index()
    similar.faiss_manager = manager

    # bulk-suggest 로직 직접 실행
    unclassified_query = text("""
        SELECT fc.id, feat.clip_embedding
        FROM file_classifications fc
        INNER JOIN image_features feat ON fc.id = feat.file_id
        WHERE fc.final_category_id IS NULL
        AND feat.clip_embedding IS NOT NULL
        LIMIT 50
    """)
    unclassified_files = test_db.execute(unclassified_query).fetchall()

    # 미분류 파일 2개 (4, 5)
    assert len(unclassified_files) == 2

    # 파일 4에 대해 유사 검색
    file4_embedding = None
    for f in unclassified_files:
        if f.id == 4:
            file4_embedding = np.frombuffer(f.clip_embedding, dtype=np.float32)
            break

    assert file4_embedding is not None
    results = manager.search_by_embedding(file4_embedding, k=5, threshold=0.7)

    # Travel 파일이 매칭되어야 함
    matched_ids = [fid for fid, _ in results]
    assert 1 in matched_ids or 2 in matched_ids

    # 매칭된 파일의 카테고리 확인
    for fid, sim in results:
        cat = test_db.execute(text(
            "SELECT final_category_id FROM file_classifications WHERE id = :id"
        ), {"id": fid}).fetchone()
        if cat and cat.final_category_id == 1:
            # Travel 카테고리 제안 확인
            assert sim >= 0.7
            break


# ================================================
# Boundary: 경계 조건
# ================================================

def test_high_threshold_filters_weak_matches(test_db, similar_pipeline_data):
    """2.1 Boundary: threshold=0.99 → 약한 매치 필터링"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager

    manager = FAISSIndexManager(test_db, dimension=512)
    manager.build_index()

    results = manager.search_similar(file_id=4, k=5, threshold=0.99)
    # 매우 높은 threshold로는 결과가 적거나 없음
    # (파일 1, 2가 유사하게 생성되므로 2개까지 허용)
    assert len(results) <= 2


# ================================================
# CrossCheck: 교차 검증
# ================================================

def test_similarity_is_symmetric(test_db, similar_pipeline_data):
    """3.1 CrossCheck: A→B 유사도 ≈ B→A 유사도"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager

    manager = FAISSIndexManager(test_db, dimension=512)
    manager.build_index()

    results_1_to_2 = manager.search_similar(file_id=1, k=5, threshold=0.0)
    results_2_to_1 = manager.search_similar(file_id=2, k=5, threshold=0.0)

    sim_1_to_2 = next((s for fid, s in results_1_to_2 if fid == 2), None)
    sim_2_to_1 = next((s for fid, s in results_2_to_1 if fid == 1), None)

    if sim_1_to_2 is not None and sim_2_to_1 is not None:
        assert abs(sim_1_to_2 - sim_2_to_1) < 0.01
