"""
FAISS 인덱스 관리 모듈

CLIP 임베딩 기반 유사 이미지 검색을 위한 FAISS 인덱스 관리
- 인덱스 빌드/저장/로드
- 유사도 검색 (k-NN)
- 30만 개 벡터, 검색 <10ms
"""

import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    print("[경고] faiss-cpu가 설치되지 않았습니다. 유사 이미지 검색 기능이 비활성화됩니다.")


class FAISSIndexManager:
    """FAISS 인덱스 관리자"""

    def __init__(
        self,
        db: Session,
        index_path: str = "data/image_classifier/faiss_index.bin",
        dimension: int = 512,  # CLIP ViT-B-32의 임베딩 차원
        use_gpu: bool = False,
    ):
        """
        Args:
            db: DB 세션
            index_path: 인덱스 파일 경로
            dimension: 임베딩 벡터 차원
            use_gpu: GPU 사용 여부
        """
        if not HAS_FAISS:
            raise ImportError(
                "faiss-cpu가 설치되지 않았습니다. "
                "pip install faiss-cpu를 실행하세요."
            )

        self.db = db
        self.index_path = Path(index_path)
        self.dimension = dimension
        self.use_gpu = use_gpu

        # 파일 ID 매핑 (인덱스 ID → 파일 ID)
        self.file_ids: List[int] = []

        # FAISS 인덱스
        self.index: Optional[faiss.Index] = None

    def build_index(self) -> dict:
        """
        DB의 모든 임베딩으로 FAISS 인덱스 빌드

        Returns:
            통계 정보
        """
        print("[FAISS] 인덱스 빌드 시작")

        # 모든 임베딩 조회
        query = text("""
            SELECT file_id, clip_embedding
            FROM image_features
            WHERE clip_embedding IS NOT NULL
            ORDER BY file_id
        """)
        rows = self.db.execute(query).fetchall()

        if not rows:
            print("[FAISS] 임베딩이 없습니다. 먼저 CLIP 워커를 실행하세요.")
            return {"total": 0, "indexed": 0}

        # 임베딩 → numpy array
        embeddings = []
        file_ids = []

        for row in rows:
            try:
                embedding = np.frombuffer(row.clip_embedding, dtype=np.float32)
                if embedding.shape[0] == self.dimension:
                    embeddings.append(embedding)
                    file_ids.append(row.file_id)
            except Exception as e:
                print(f"[FAISS] 임베딩 로드 오류 (file_id={row.file_id}): {e}")

        if not embeddings:
            print("[FAISS] 유효한 임베딩이 없습니다.")
            return {"total": len(rows), "indexed": 0}

        embeddings_np = np.vstack(embeddings).astype("float32")
        print(f"[FAISS] 임베딩 로드 완료: {embeddings_np.shape}")

        # 정규화 (cosine similarity를 위해)
        faiss.normalize_L2(embeddings_np)

        # FAISS 인덱스 생성 (Inner Product = Cosine Similarity after normalization)
        self.index = faiss.IndexFlatIP(self.dimension)

        # GPU 사용
        if self.use_gpu and faiss.get_num_gpus() > 0:
            print("[FAISS] GPU 사용")
            self.index = faiss.index_cpu_to_gpu(faiss.StandardGpuResources(), 0, self.index)

        # 인덱스에 추가
        self.index.add(embeddings_np)
        self.file_ids = file_ids

        print(f"[FAISS] 인덱스 빌드 완료: {self.index.ntotal}개")

        # 인덱스 저장
        self.save_index()

        return {
            "total": len(rows),
            "indexed": self.index.ntotal,
        }

    def save_index(self):
        """인덱스를 파일로 저장"""
        if self.index is None:
            print("[FAISS] 저장할 인덱스가 없습니다.")
            return

        # 디렉토리 생성
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # GPU 인덱스 → CPU로 변환 후 저장
        index_to_save = self.index
        if self.use_gpu and faiss.get_num_gpus() > 0:
            index_to_save = faiss.index_gpu_to_cpu(self.index)

        # 저장
        faiss.write_index(index_to_save, str(self.index_path))

        # 파일 ID 매핑 저장
        mapping_path = self.index_path.with_suffix(".npy")
        np.save(mapping_path, np.array(self.file_ids, dtype=np.int64))

        print(f"[FAISS] 인덱스 저장 완료: {self.index_path}")

    def load_index(self) -> bool:
        """인덱스를 파일에서 로드"""
        if not self.index_path.exists():
            print(f"[FAISS] 인덱스 파일이 없습니다: {self.index_path}")
            return False

        # 인덱스 로드
        self.index = faiss.read_index(str(self.index_path))

        # GPU 사용
        if self.use_gpu and faiss.get_num_gpus() > 0:
            print("[FAISS] GPU 사용")
            self.index = faiss.index_cpu_to_gpu(faiss.StandardGpuResources(), 0, self.index)

        # 파일 ID 매핑 로드
        mapping_path = self.index_path.with_suffix(".npy")
        if mapping_path.exists():
            self.file_ids = np.load(mapping_path).tolist()
        else:
            print("[FAISS 경고] 파일 ID 매핑이 없습니다. 검색 결과가 부정확할 수 있습니다.")
            self.file_ids = list(range(self.index.ntotal))

        print(f"[FAISS] 인덱스 로드 완료: {self.index.ntotal}개")
        return True

    def search_similar(
        self,
        file_id: int,
        k: int = 10,
        threshold: float = 0.7,
    ) -> List[Tuple[int, float]]:
        """
        특정 파일과 유사한 이미지 검색

        Args:
            file_id: 기준 파일 ID
            k: 반환할 결과 수
            threshold: 유사도 임계값 (0~1, cosine similarity)

        Returns:
            (file_id, similarity) 리스트
        """
        if self.index is None:
            if not self.load_index():
                print("[FAISS] 인덱스를 로드할 수 없습니다.")
                return []

        # 임베딩 조회
        query = text("SELECT clip_embedding FROM image_features WHERE file_id = :file_id")
        result = self.db.execute(query, {"file_id": file_id}).fetchone()

        if not result or not result.clip_embedding:
            print(f"[FAISS] 파일 ID {file_id}의 임베딩이 없습니다.")
            return []

        # 임베딩 → numpy array
        embedding = np.frombuffer(result.clip_embedding, dtype=np.float32).reshape(1, -1)

        # 정규화
        faiss.normalize_L2(embedding)

        # 검색
        distances, indices = self.index.search(embedding, k + 1)  # +1은 자기 자신 제외용

        # 결과 변환
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue

            result_file_id = self.file_ids[idx]

            # 자기 자신 제외
            if result_file_id == file_id:
                continue

            # 유사도 (Inner Product = Cosine Similarity)
            similarity = float(dist)

            # 임계값 필터링
            if similarity >= threshold:
                results.append((result_file_id, similarity))

        return results

    def search_by_embedding(
        self,
        embedding: np.ndarray,
        k: int = 10,
        threshold: float = 0.7,
    ) -> List[Tuple[int, float]]:
        """
        임베딩 벡터로 유사 이미지 검색

        Args:
            embedding: 512차원 임베딩 벡터
            k: 반환할 결과 수
            threshold: 유사도 임계값

        Returns:
            (file_id, similarity) 리스트
        """
        if self.index is None:
            if not self.load_index():
                print("[FAISS] 인덱스를 로드할 수 없습니다.")
                return []

        # 정규화
        embedding = embedding.astype("float32").reshape(1, -1)
        faiss.normalize_L2(embedding)

        # 검색
        distances, indices = self.index.search(embedding, k)

        # 결과 변환
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue

            result_file_id = self.file_ids[idx]
            similarity = min(1.0, float(dist))  # 부동소수점 오차 클립

            if similarity >= threshold:
                results.append((result_file_id, similarity))

        return results
