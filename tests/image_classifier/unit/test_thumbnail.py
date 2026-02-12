"""썸네일 생성 테스트"""
import pytest
from pathlib import Path
from PIL import Image
from sqlalchemy import text
from app.modules.image_classifier.workers.thumbnail import ThumbnailWorker, get_thumbnail_path
from app.modules.image_classifier.config import ImageClassifierSettings


# ================================================
# Right: 기본 동작
# ================================================

def test_thumbnail_created_as_jpeg(test_db, tmp_path):
    """8.1 Right: 출력 파일 확장자 .jpg"""
    # 원본 이미지 생성 (PNG)
    img = Image.new("RGB", (800, 600), color="orange")
    original = tmp_path / "original.png"
    img.save(str(original))

    # DB에 파일 등록
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, status)
        VALUES (1, :path, 'hash', 'pending')
    """), {"path": str(original)})
    test_db.commit()

    # 썸네일 생성
    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일 파일 확인
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    assert thumbnail_path.exists()
    assert thumbnail_path.suffix == ".jpg"


def test_thumbnail_size_300x300(test_db, tmp_path):
    """8.2 Right: 300x300 이하 크기"""
    # 큰 이미지 생성 (1000x1000)
    img = Image.new("RGB", (1000, 1000), color="blue")
    original = tmp_path / "large.jpg"
    img.save(str(original))

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일 크기 확인
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    with Image.open(thumbnail_path) as thumb:
        assert thumb.width <= 300
        assert thumb.height <= 300


def test_exif_rotation_corrected(test_db, tmp_path):
    """8.3 Right: 회전 이미지 → 정상 방향"""
    import piexif

    # 90도 회전된 이미지 생성
    img = Image.new("RGB", (800, 600), color="green")  # 가로가 더 김
    exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}  # 6 = 90도 회전
    exif_bytes = piexif.dump(exif_dict)

    original = tmp_path / "rotated.jpg"
    img.save(str(original), exif=exif_bytes)

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일이 자동 회전되었는지 확인
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    with Image.open(thumbnail_path) as thumb:
        # 90도 회전되면 width와 height가 바뀜
        assert thumb.height > thumb.width  # 원본은 800x600이었지만, 회전 후 600x800


def test_rgba_converted_to_rgb(test_db, tmp_path):
    """8.4 Right: RGBA/P → RGB 변환"""
    # RGBA 이미지 생성
    img = Image.new("RGBA", (400, 400), color=(255, 0, 0, 128))
    original = tmp_path / "rgba.png"
    img.save(str(original))

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일이 RGB 모드인지 확인
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    with Image.open(thumbnail_path) as thumb:
        assert thumb.mode == "RGB"


def test_thumbnail_path_format(test_db, tmp_path):
    """8.5 Right: `{file_id}.jpg` 형식"""
    img = Image.new("RGB", (200, 200), color="yellow")
    original = tmp_path / "image.jpg"
    img.save(str(original))

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"

    # get_thumbnail_path 함수 테스트
    thumbnail_path = get_thumbnail_path(file_id=42, settings=settings)

    assert thumbnail_path.name == "42.jpg"
    assert thumbnail_path.parent == settings.THUMBNAIL_DIR


# ================================================
# Boundary: 경계 조건
# ================================================

def test_very_small_image(test_db, tmp_path):
    """8.6 Boundary: 100x100 이미지 → 썸네일 생성"""
    # 작은 이미지 (이미 300x300 이하)
    img = Image.new("RGB", (100, 100), color="pink")
    original = tmp_path / "small.jpg"
    img.save(str(original))

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일 생성됨
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    assert thumbnail_path.exists()

    # 크기는 원본과 동일하거나 작음
    with Image.open(thumbnail_path) as thumb:
        assert thumb.width <= 100
        assert thumb.height <= 100


def test_very_large_image(test_db, tmp_path):
    """8.7 Boundary: 10000x10000 → 정상 리사이즈"""
    # 매우 큰 이미지 (메모리 절약을 위해 5000x5000으로 축소)
    img = Image.new("RGB", (5000, 5000), color="cyan")
    original = tmp_path / "huge.jpg"
    img.save(str(original))

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    worker._create_thumbnail(1, original)

    # 썸네일이 300x300 이하로 리사이즈됨
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    assert thumbnail_path.exists()

    with Image.open(thumbnail_path) as thumb:
        assert thumb.width <= 300
        assert thumb.height <= 300


# ================================================
# Error: 예외 처리
# ================================================

def test_corrupted_image_skip(test_db, tmp_path):
    """8.8 Error: 손상 이미지 → 에러 로그, 건너뜀"""
    # 손상된 이미지 파일
    corrupted = tmp_path / "corrupted.jpg"
    with open(corrupted, "wb") as f:
        f.write(b"not a valid image")

    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    # 예외 발생해야 함
    with pytest.raises(Exception):
        worker._create_thumbnail(1, corrupted)

    # 썸네일 파일이 생성되지 않음
    thumbnail_path = settings.THUMBNAIL_DIR / "1.jpg"
    assert not thumbnail_path.exists()


# ================================================
# Inverse: DB와 파일명 일치
# ================================================

@pytest.mark.asyncio
async def test_thumbnail_matches_file_id(test_db, tmp_path):
    """8.9 Inverse: DB file_id와 썸네일 파일명 일치"""
    # 여러 파일 생성
    for file_id in [10, 20, 30]:
        img = Image.new("RGB", (200, 200), color="gray")
        original = tmp_path / f"file{file_id}.jpg"
        img.save(str(original))

        # DB 등록
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, 'hash', 'pending')
        """), {"id": file_id, "path": str(original)})

    test_db.commit()

    # 썸네일 생성
    settings = ImageClassifierSettings()
    settings.THUMBNAIL_DIR = tmp_path / "thumbs"
    worker = ThumbnailWorker(test_db, settings)

    await worker.process_pending_files(batch_size=10)

    # 각 file_id에 대응하는 썸네일 파일 확인
    for file_id in [10, 20, 30]:
        thumbnail_path = settings.THUMBNAIL_DIR / f"{file_id}.jpg"
        assert thumbnail_path.exists()

        # DB에서 파일 경로 조회
        db_result = test_db.execute(text("""
            SELECT file_path FROM file_classifications WHERE id = :fid
        """), {"fid": file_id}).fetchone()

        assert db_result is not None
