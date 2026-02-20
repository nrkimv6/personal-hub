"""FAISS 인덱스 테스트"""
import pytest
import numpy as np
from pathlib import Path
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
def faiss_manager(test_db, tmp_path):
    """FAISS 인덱스 매니저 생성"""
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager

    index_path = tmp_path / "test_index.faiss"
    manager = FAISSIndexManager(
        db=test_db,
        index_path=str(index_path),
        dimension=512,
        use_gpu=False  # 테스트는 CPU 모드
    )
    return manager


@pytest.fixture
def seeded_embeddings(test_db):
    """임베딩이 있는 파일 데이터 생성"""
    # 5개 파일 생성
    for file_id in range(1, 6):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, 'hash', 'pending')
        """), {"id": file_id, "path": f"/test/file{file_id}.jpg"})

        # 임베딩 생성 (랜덤 512차원 벡터)
        embedding = np.random.rand(512).astype(np.float32)
        # 정규화
        embedding = embedding / np.linalg.norm(embedding)

        # 첫 번째와 두 번째 파일은 유사하게 (거의 동일)
        if file_id == 2:
            # file 1의 임베딩 조회
            result = test_db.execute(text("""
                SELECT clip_embedding FROM image_features WHERE file_id = 1
            """)).fetchone()
            embedding = np.frombuffer(result.clip_embedding, dtype=np.float32).copy()  # copy() 추가
            # 약간 변형
            embedding += np.random.rand(512).astype(np.float32) * 0.01
            embedding = embedding / np.linalg.norm(embedding)

        embedding_bytes = embedding.tobytes()
        test_db.execute(text("""
            INSERT INTO image_features (file_id, clip_embedding)
            VALUES (:file_id, :embedding)
        """), {"file_id": file_id, "embedding": embedding_bytes})

    test_db.commit()


# ================================================
# Right: 기본 동작
# ================================================

def test_build_index_creates_file(faiss_manager, seeded_embeddings):
    """11.1 Right: .faiss 파일 생성"""
    result = faiss_manager.build_index()

    assert result["total"] == 5
    assert result["indexed"] == 5

    # 인덱스 파일 생성 확인
    assert faiss_manager.index_path.exists()
    assert faiss_manager.index_path.suffix == ".faiss"


def test_build_index_file_id_mapping(faiss_manager, seeded_embeddings):
    """11.2 Right: .npy 매핑 파일 생성"""
    faiss_manager.build_index()

    # 매핑 파일 경로
    mapping_path = faiss_manager.index_path.with_suffix(".npy")

    # 매핑 파일 생성 확인
    assert mapping_path.exists()

    # 매핑 파일 로드
    file_ids = np.load(mapping_path)
    assert len(file_ids) == 5
    assert list(file_ids) == [1, 2, 3, 4, 5]


def test_search_returns_k_results(faiss_manager, seeded_embeddings):
    """11.3 Right: k=10 → 10개 이하 결과"""
    faiss_manager.build_index()

    # file 1과 유사한 이미지 검색 (k=10)
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # 5개 파일 중 자기 자신 제외 → 최대 4개
    assert len(results) <= 4


def test_search_excludes_self(faiss_manager, seeded_embeddings):
    """11.4 Right: 자기 자신 제외"""
    faiss_manager.build_index()

    # file 1과 유사한 이미지 검색
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # 결과에 자기 자신(file_id=1)이 없어야 함
    result_file_ids = [file_id for file_id, _ in results]
    assert 1 not in result_file_ids


def test_search_threshold_filter(faiss_manager, seeded_embeddings):
    """11.5 Right: threshold 이하만 반환"""
    faiss_manager.build_index()

    # threshold=0.9로 검색 (매우 유사한 것만)
    results_high = faiss_manager.search_similar(file_id=1, k=10, threshold=0.9)

    # threshold=0.0으로 검색 (모두 반환)
    results_low = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # high threshold는 low threshold보다 결과가 적거나 같아야 함
    assert len(results_high) <= len(results_low)

    # high threshold 결과의 모든 유사도는 0.9 이상이어야 함
    for _, similarity in results_high:
        assert similarity >= 0.9


def test_l2_normalization(faiss_manager, seeded_embeddings):
    """11.6 Right: 정규화 후 inner product = cosine similarity"""
    faiss_manager.build_index()

    # file 1의 임베딩 조회
    from app.modules.image_classifier.workers.faiss_index import FAISSIndexManager
    query = text("SELECT clip_embedding FROM image_features WHERE file_id = 1")
    result = faiss_manager.db.execute(query).fetchone()
    embedding = np.frombuffer(result.clip_embedding, dtype=np.float32)

    # L2 norm 확인 (이미 정규화되어 있어야 함)
    norm = np.linalg.norm(embedding)
    assert 0.99 <= norm <= 1.01  # norm ≈ 1.0

    # 검색 결과의 유사도는 0~1 사이여야 함 (cosine similarity)
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)
    for _, similarity in results:
        assert 0.0 <= similarity <= 1.0


# ================================================
# Boundary: 경계 조건
# ================================================

def test_empty_index_build(faiss_manager, test_db):
    """11.7 Boundary: 임베딩 0개 → 에러 처리"""
    # 임베딩 없이 인덱스 빌드 시도
    result = faiss_manager.build_index()

    assert result["total"] == 0
    assert result["indexed"] == 0


def test_search_k_equals_1(faiss_manager, seeded_embeddings):
    """11.8 Boundary: k=1 → 가장 유사한 1개"""
    faiss_manager.build_index()

    # k=1로 검색
    results = faiss_manager.search_similar(file_id=1, k=1, threshold=0.0)

    # 최대 1개 결과
    assert len(results) <= 1


def test_threshold_0(faiss_manager, seeded_embeddings):
    """11.9 Boundary: threshold=0 → 전부 반환"""
    faiss_manager.build_index()

    # threshold=0으로 검색
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # 자기 자신 제외한 모든 파일 반환 (4개)
    assert len(results) == 4


def test_threshold_1(faiss_manager, seeded_embeddings):
    """11.10 Boundary: threshold=1.0 → 거의 없음"""
    faiss_manager.build_index()

    # threshold=1.0으로 검색 (완전히 동일한 것만)
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=1.0)

    # 완전히 동일한 이미지는 없으므로 결과가 매우 적거나 없음
    # (file 2가 유사하게 만들어졌지만 1.0은 아님)
    assert len(results) <= 1


# ================================================
# Inverse: 저장/로드
# ================================================

def test_save_load_index_roundtrip(faiss_manager, seeded_embeddings):
    """11.11 Inverse: 저장→로드→검색 결과 동일"""
    # 인덱스 빌드 및 저장
    faiss_manager.build_index()

    # 검색 결과 저장
    results_before = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # 인덱스 초기화
    faiss_manager.index = None
    faiss_manager.file_ids = []

    # 인덱스 로드
    loaded = faiss_manager.load_index()
    assert loaded is True

    # 검색 결과 비교
    results_after = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    # 결과가 동일해야 함
    assert len(results_before) == len(results_after)

    # file_id 순서는 다를 수 있지만, 집합으로 비교
    ids_before = {file_id for file_id, _ in results_before}
    ids_after = {file_id for file_id, _ in results_after}
    assert ids_before == ids_after


# ================================================
# Error: 예외 처리
# ================================================

def test_load_nonexistent_index(faiss_manager):
    """11.12 Error: 인덱스 파일 없음 → False"""
    # 인덱스 파일이 없는 상태에서 로드 시도
    loaded = faiss_manager.load_index()

    assert loaded is False


def test_search_by_embedding_returns_results(faiss_manager, seeded_embeddings):
    """11.14 Right: search_by_embedding() — 임베딩 벡터로 검색"""
    faiss_manager.build_index()

    # file 1의 임베딩 가져오기
    query = text("SELECT clip_embedding FROM image_features WHERE file_id = 1")
    result = faiss_manager.db.execute(query).fetchone()
    embedding = np.frombuffer(result.clip_embedding, dtype=np.float32)

    # search_by_embedding으로 검색
    results = faiss_manager.search_by_embedding(embedding, k=5, threshold=0.0)

    assert len(results) > 0
    # 모든 결과가 (file_id, similarity) 튜플
    for file_id, similarity in results:
        assert isinstance(file_id, int)
        assert 0.0 <= similarity <= 1.0


def test_search_by_embedding_threshold(faiss_manager, seeded_embeddings):
    """11.15 Right: search_by_embedding() — threshold 필터링"""
    faiss_manager.build_index()

    # file 1의 임베딩
    query = text("SELECT clip_embedding FROM image_features WHERE file_id = 1")
    result = faiss_manager.db.execute(query).fetchone()
    embedding = np.frombuffer(result.clip_embedding, dtype=np.float32)

    results_low = faiss_manager.search_by_embedding(embedding, k=5, threshold=0.0)
    results_high = faiss_manager.search_by_embedding(embedding, k=5, threshold=0.95)

    assert len(results_high) <= len(results_low)

    for _, similarity in results_high:
        assert similarity >= 0.95


def test_search_by_embedding_without_index(faiss_manager):
    """11.16 Error: search_by_embedding() — 인덱스 없음 → 빈 결과"""
    embedding = np.random.rand(512).astype(np.float32)
    results = faiss_manager.search_by_embedding(embedding, k=5, threshold=0.0)
    assert results == []


def test_search_without_index(faiss_manager, seeded_embeddings):
    """11.13 Error: 인덱스 없이 검색 → 빈 결과"""
    # 인덱스를 빌드하지 않은 상태에서 검색 시도
    # (load_index 실패 → 빈 리스트 반환)
    results = faiss_manager.search_similar(file_id=1, k=10, threshold=0.0)

    assert results == []
