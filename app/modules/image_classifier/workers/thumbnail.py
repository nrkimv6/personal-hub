"""
썸네일 생성 워커

- Pillow로 리사이즈 (300x300 기본)
- EXIF 회전 보정 (ImageOps.exif_transpose)
- data/image_classifier/thumbnails/{file_id}.jpg에 저장
- 전체 파일 반복 처리 + 진행률 콜백 + 중지 지원
"""

import asyncio
from pathlib import Path
from typing import Callable, Optional

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

    async def process_all_pending(
        self,
        batch_size: int = 500,
        cancel_event: Optional[asyncio.Event] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        """
        썸네일이 없는 모든 파일을 배치 처리

        Args:
            batch_size: DB 조회 배치 크기
            cancel_event: 중지 신호
            on_progress: 콜백 (processed, total)

        Returns:
            {"processed": int, "skipped": int, "failed": int, "total": int}
        """
        # 전체 파일 수 파악
        total = self.db.execute(
            text("SELECT COUNT(*) FROM file_classifications")
        ).scalar() or 0

        if total == 0:
            return {"processed": 0, "skipped": 0, "failed": 0, "total": 0}

        processed = 0
        skipped = 0
        failed = 0
        offset = 0

        while offset < total:
            if cancel_event and cancel_event.is_set():
                print(f"[썸네일] 중지됨: {processed}/{total}")
                break

            rows = self.db.execute(
                text("SELECT id, file_path FROM file_classifications LIMIT :limit OFFSET :offset"),
                {"limit": batch_size, "offset": offset}
            ).fetchall()

            if not rows:
                break

            for row in rows:
                if cancel_event and cancel_event.is_set():
                    break

                file_id = row.id
                thumb_path = self.thumbnail_dir / f"{file_id}.jpg"

                # 이미 존재하면 스킵
                if thumb_path.exists():
                    skipped += 1
                    processed += 1
                    if on_progress:
                        on_progress(processed, total)
                    continue

                file_path = Path(row.file_path)
                if not file_path.exists():
                    failed += 1
                    processed += 1
                    if on_progress:
                        on_progress(processed, total)
                    continue

                try:
                    self._create_thumbnail(file_id, file_path)
                    processed += 1
                except Exception as e:
                    print(f"[썸네일 오류] {file_path}: {e}")
                    failed += 1
                    processed += 1

                if on_progress:
                    on_progress(processed, total)

                # 비동기 양보 (매 50개마다)
                if processed % 50 == 0:
                    await asyncio.sleep(0)

            offset += batch_size

        result = {
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "created": processed - skipped - failed,
        }
        print(f"[썸네일 완료] 생성: {result['created']}, 스킵: {skipped}, 실패: {failed}, 전체: {total}")
        return result

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
