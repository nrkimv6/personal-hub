"""
썸네일 생성 워커

- Pillow로 리사이즈 (300x300 기본)
- EXIF 회전 보정 (ImageOps.exif_transpose)
- data/image_classifier/thumbnails/{file_id}.jpg에 저장
"""

from pathlib import Path
from PIL import Image, ImageOps
from sqlalchemy import text
from sqlalchemy.orm import Session


class ThumbnailWorker:
    """썸네일 생성 백그라운드 워커"""

    def __init__(self, db: Session, settings):
        self.db = db
        self.thumbnail_size = settings.THUMBNAIL_SIZE  # (300, 300)
        self.thumbnail_quality = settings.THUMBNAIL_QUALITY  # 85
        self.thumbnail_dir = settings.THUMBNAIL_DIR  # data/image_classifier/thumbnails/

        # 썸네일 디렉토리 생성
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

    async def process_pending_files(self, batch_size: int = 100):
        """
        썸네일이 없는 파일 배치 처리

        Args:
            batch_size: 배치 크기
        """
        # 썸네일 파일이 없는 파일 조회
        result = self.db.execute(
            text("""
                SELECT id, file_path
                FROM file_classifications
                WHERE id NOT IN (
                    SELECT DISTINCT file_id
                    FROM (
                        SELECT id AS file_id
                        FROM file_classifications
                        WHERE id IN (
                            SELECT CAST(REPLACE(name, '.jpg', '') AS INTEGER) AS file_id
                            FROM (
                                SELECT name FROM pragma_file_list(:thumb_dir)
                                WHERE name LIKE '%.jpg'
                            )
                        )
                    )
                )
                LIMIT :batch_size
            """),
            {"thumb_dir": str(self.thumbnail_dir), "batch_size": batch_size}
        ).fetchall()

        # 위 쿼리가 복잡하므로 단순화: 모든 파일을 순회하며 썸네일 파일 존재 여부 확인
        result = self.db.execute(
            text("SELECT id, file_path FROM file_classifications LIMIT :batch_size"),
            {"batch_size": batch_size}
        ).fetchall()

        pending_files = [
            row for row in result
            if not (self.thumbnail_dir / f"{row.id}.jpg").exists()
        ]

        if not pending_files:
            print("[썸네일] 처리할 파일 없음")
            return

        print(f"[썸네일] 처리 대상: {len(pending_files)}개")

        for row in pending_files:
            file_id = row.id
            file_path = Path(row.file_path)

            if not file_path.exists():
                print(f"[경고] 파일 없음: {file_path}")
                continue

            try:
                self._create_thumbnail(file_id, file_path)
            except Exception as e:
                print(f"[오류] 썸네일 생성 실패: {file_path} - {e}")

        print("[썸네일] 배치 완료")

    def _create_thumbnail(self, file_id: int, file_path: Path):
        """
        썸네일 생성 및 저장

        Args:
            file_id: file_classifications.id
            file_path: 원본 이미지 경로
        """
        with Image.open(file_path) as img:
            # EXIF 회전 보정 (EXIF Orientation 태그에 따라 자동 회전)
            img = ImageOps.exif_transpose(img)

            # RGB 변환 (RGBA, P 모드 등 처리)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # 썸네일 생성 (비율 유지하며 리사이즈)
            img.thumbnail(self.thumbnail_size, Image.Resampling.LANCZOS)

            # 저장 경로
            thumbnail_path = self.thumbnail_dir / f"{file_id}.jpg"

            # JPEG로 저장
            img.save(thumbnail_path, "JPEG", quality=self.thumbnail_quality, optimize=True)

        # 파일 크기 로그
        thumb_size_kb = thumbnail_path.stat().st_size / 1024
        print(f"[썸네일] 생성: {file_id}.jpg ({thumb_size_kb:.1f} KB)")


def get_thumbnail_path(file_id: int, settings) -> Path:
    """
    썸네일 파일 경로 반환

    Args:
        file_id: file_classifications.id
        settings: ImageClassifierSettings

    Returns:
        썸네일 파일 경로 (존재하지 않을 수 있음)
    """
    return settings.THUMBNAIL_DIR / f"{file_id}.jpg"
