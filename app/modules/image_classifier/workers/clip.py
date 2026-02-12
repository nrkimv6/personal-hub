"""
CLIP 임베딩 계산 워커

sentence-transformers의 clip-ViT-B-32 모델을 사용하여
이미지의 의미적 임베딩을 계산합니다.

GPU (GTX 1660 Super) 사용 시 ~150 이미지/초 (배치 64~128)
30만 장 기준 ~35분 소요
"""

import asyncio
import numpy as np
from pathlib import Path
from typing import Optional
from PIL import Image
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False
    print("[경고] sentence-transformers가 설치되지 않았습니다. CLIP 임베딩 기능이 비활성화됩니다.")


class CLIPEmbeddingWorker:
    """CLIP 임베딩 계산 워커"""

    def __init__(
        self,
        db: Session,
        model_name: str = "clip-ViT-B-32",
        batch_size: int = 64,
        device: Optional[str] = None,
    ):
        """
        Args:
            db: DB 세션
            model_name: CLIP 모델 이름
            batch_size: 배치 크기 (GPU 메모리에 따라 조정)
            device: 'cuda' 또는 'cpu' (None이면 자동 감지)
        """
        self.db = db
        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device

        if not HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers가 설치되지 않았습니다. "
                "pip install sentence-transformers를 실행하세요."
            )

        # 모델 로드
        print(f"[CLIP] 모델 로드 중: {model_name}")
        self.model = SentenceTransformer(model_name, device=device)
        print(f"[CLIP] 모델 로드 완료 (device: {self.model.device})")

    def compute_embedding(self, image_path: str) -> Optional[np.ndarray]:
        """
        단일 이미지의 CLIP 임베딩 계산

        Args:
            image_path: 이미지 파일 경로

        Returns:
            512차원 임베딩 벡터 (numpy array) 또는 None (실패 시)
        """
        try:
            image = Image.open(image_path).convert("RGB")
            embedding = self.model.encode(image, convert_to_numpy=True)
            return embedding
        except Exception as e:
            print(f"[CLIP 오류] {image_path}: {e}")
            return None

    async def compute_all_embeddings(
        self,
        on_progress: Optional[callable] = None
    ) -> dict:
        """
        DB의 모든 파일에 대해 CLIP 임베딩 계산

        Args:
            on_progress: 진행 상황 콜백 (total, processed, current_file)

        Returns:
            통계 정보
        """
        # 임베딩이 없는 파일 조회
        query = text("""
            SELECT fc.id, fc.file_path
            FROM file_classifications fc
            LEFT JOIN image_features feat ON fc.id = feat.file_id
            WHERE feat.clip_embedding IS NULL OR feat.clip_embedding = ''
            ORDER BY fc.id
        """)
        files = self.db.execute(query).fetchall()

        total = len(files)
        print(f"[CLIP] 임베딩 계산 시작: {total}개 파일")

        if total == 0:
            return {"total": 0, "processed": 0, "failed": 0, "skipped": 0}

        processed = 0
        failed = 0
        batch_paths = []
        batch_ids = []

        for file in files:
            file_id = file.id
            file_path = file.file_path

            # 파일 존재 확인
            if not Path(file_path).exists():
                failed += 1
                continue

            batch_paths.append(file_path)
            batch_ids.append(file_id)

            # 배치 크기에 도달하면 처리
            if len(batch_paths) >= self.batch_size:
                await self._process_batch(batch_paths, batch_ids)
                processed += len(batch_paths)

                batch_paths = []
                batch_ids = []

                # 진행 상황 콜백
                if on_progress:
                    on_progress(total, processed, None)

                # DB 커밋 (배치마다)
                self.db.commit()

                # 비동기 양보
                await asyncio.sleep(0.01)

        # 남은 배치 처리
        if batch_paths:
            await self._process_batch(batch_paths, batch_ids)
            processed += len(batch_paths)
            self.db.commit()

        print(f"[CLIP] 임베딩 계산 완료: {processed}/{total} (실패: {failed})")

        return {
            "total": total,
            "processed": processed,
            "failed": failed,
            "skipped": 0,
        }

    async def _process_batch(self, image_paths: list[str], file_ids: list[int]):
        """
        배치 이미지 임베딩 계산 및 DB 저장

        Args:
            image_paths: 이미지 경로 리스트
            file_ids: 파일 ID 리스트
        """
        # 이미지 로드
        images = []
        valid_ids = []

        for i, path in enumerate(image_paths):
            try:
                img = Image.open(path).convert("RGB")
                images.append(img)
                valid_ids.append(file_ids[i])
            except Exception as e:
                print(f"[CLIP 배치 오류] {path}: {e}")

        if not images:
            return

        # 배치 임베딩 계산
        try:
            embeddings = self.model.encode(
                images,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as e:
            print(f"[CLIP 배치 계산 오류] {e}")
            return

        # DB 저장
        for file_id, embedding in zip(valid_ids, embeddings):
            # BLOB으로 저장 (numpy array → bytes)
            embedding_bytes = embedding.tobytes()

            # image_features 테이블에 UPSERT
            upsert_query = text("""
                INSERT INTO image_features (file_id, clip_embedding, computed_at)
                VALUES (:file_id, :embedding, datetime('now'))
                ON CONFLICT(file_id) DO UPDATE SET
                    clip_embedding = :embedding,
                    computed_at = datetime('now')
            """)
            self.db.execute(upsert_query, {
                "file_id": file_id,
                "embedding": embedding_bytes,
            })

    def get_embedding(self, file_id: int) -> Optional[np.ndarray]:
        """
        파일 ID로 임베딩 조회

        Args:
            file_id: 파일 ID

        Returns:
            512차원 임베딩 벡터 (numpy array) 또는 None
        """
        query = text("SELECT clip_embedding FROM image_features WHERE file_id = :file_id")
        result = self.db.execute(query, {"file_id": file_id}).fetchone()

        if not result or not result.clip_embedding:
            return None

        # BLOB → numpy array
        embedding = np.frombuffer(result.clip_embedding, dtype=np.float32)
        return embedding
