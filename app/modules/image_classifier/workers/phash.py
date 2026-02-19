"""
pHash (Perceptual Hash) 계산 워커

- imagehash 라이브러리 사용
- 배치 처리로 성능 최적화
- DB에 hex 문자열로 저장
"""

from pathlib import Path
from typing import Callable, List, Optional
import imagehash
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session


class PHashWorker:
    """pHash 계산 백그라운드 워커"""

    def __init__(self, db: Session, settings):
        self.db = db
        self.hash_size = settings.PHASH_HASH_SIZE  # 기본 16

    def process_pending_files(
        self,
        batch_size: int = 100,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        """
        pHash가 없는 파일 배치 처리 (동기)

        Args:
            batch_size: 배치 크기
            on_progress: 진행률 콜백 (processed, total)
        """
        # pHash가 없는 파일 전체 개수 파악
        total = self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM file_classifications fc
                LEFT JOIN image_features ifeat ON fc.id = ifeat.file_id
                WHERE ifeat.phash IS NULL
            """)
        ).scalar() or 0

        if total == 0:
            print("[pHash] 처리할 파일 없음")
            return

        print(f"[pHash] 처리 대상: {total}개")
        processed = 0

        offset = 0
        while True:
            # 배치 조회
            result = self.db.execute(
                text("""
                    SELECT fc.id, fc.file_path
                    FROM file_classifications fc
                    LEFT JOIN image_features ifeat ON fc.id = ifeat.file_id
                    WHERE ifeat.phash IS NULL
                    LIMIT :batch_size
                """),
                {"batch_size": batch_size}
            ).fetchall()

            if not result:
                break

            for row in result:
                file_id = row.id
                file_path = Path(row.file_path)

                if not file_path.exists():
                    print(f"[경고] 파일 없음: {file_path}")
                    processed += 1
                    if on_progress:
                        on_progress(processed, total)
                    continue

                try:
                    phash_hex = self._compute_phash(file_path)
                    self._save_phash(file_id, phash_hex)
                except Exception as e:
                    print(f"[오류] pHash 계산 실패: {file_path} - {e}")

                processed += 1
                if on_progress:
                    on_progress(processed, total)

            # 다음 배치에서 WHERE ifeat.phash IS NULL이 자동으로 이미 처리된 것 제외
            # → 새로 저장된 것들이 다음 쿼리에서 필터링됨

        print(f"[pHash] 완료: {processed}/{total}")

    @staticmethod
    def compute_phash_from_image(img: Image.Image, hash_size: int = 16) -> str:
        """
        Pillow Image 객체에서 직접 pHash 계산 (정적 메서드)

        썸네일 리사이즈 전 원본 해상도에서 호출해야 정확도가 높음.

        Args:
            img: Pillow Image 객체 (원본 해상도)
            hash_size: 해시 크기 (8, 16, 32 등. 클수록 정밀), 기본값 16

        Returns:
            pHash hex 문자열
        """
        phash = imagehash.phash(img, hash_size=hash_size)
        return str(phash)  # hex 문자열로 변환

    def _compute_phash(self, file_path: Path) -> str:
        """
        pHash 계산 (파일 경로로 호출)

        Args:
            file_path: 이미지 파일 경로

        Returns:
            pHash hex 문자열
        """
        with Image.open(file_path) as img:
            # 정적 메서드를 통해 계산 (코드 재사용)
            return self.compute_phash_from_image(img, hash_size=self.hash_size)

    def _save_phash(self, file_id: int, phash_hex: str):
        """
        pHash를 image_features 테이블에 저장

        Args:
            file_id: file_classifications.id
            phash_hex: pHash hex 문자열
        """
        # INSERT OR REPLACE (SQLite)
        self.db.execute(
            text("""
                INSERT INTO image_features (file_id, phash)
                VALUES (:file_id, :phash)
                ON CONFLICT(file_id)
                DO UPDATE SET phash = :phash
            """),
            {"file_id": file_id, "phash": phash_hex}
        )
        self.db.commit()


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    두 pHash 간 Hamming Distance 계산

    Args:
        hash1, hash2: pHash hex 문자열

    Returns:
        Hamming distance (비트 차이 수)
    """
    # imagehash 라이브러리의 hex 값을 직접 XOR하여 비트 차이 계산
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    return h1 - h2  # imagehash의 __sub__는 Hamming distance 반환


def find_similar_images(
    db: Session,
    target_phash: str,
    threshold: int = 10,
    limit: int = 10
) -> List[dict]:
    """
    유사 이미지 검색 (pHash 기반)

    Args:
        db: DB 세션
        target_phash: 검색할 pHash
        threshold: Hamming distance 임계값 (≤10: 매우 유사)
        limit: 최대 반환 수

    Returns:
        [{"file_id": int, "file_path": str, "distance": int}]
    """
    # 전체 pHash 조회 (향후 FAISS나 인덱스 최적화 가능)
    result = db.execute(
        text("SELECT file_id, phash FROM image_features WHERE phash IS NOT NULL")
    ).fetchall()

    similar = []
    for row in result:
        distance = hamming_distance(target_phash, row.phash)
        if distance <= threshold:
            # 파일 경로 조회
            file_info = db.execute(
                text("SELECT file_path FROM file_classifications WHERE id = :file_id"),
                {"file_id": row.file_id}
            ).fetchone()

            similar.append({
                "file_id": row.file_id,
                "file_path": file_info.file_path if file_info else None,
                "distance": distance,
            })

    # 거리 오름차순 정렬 후 제한
    similar.sort(key=lambda x: x["distance"])
    return similar[:limit]
