"""메타데이터 추출 테스트"""
import pytest
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from app.modules.image_classifier.workers.metadata import MetadataExtractor


# ================================================
# Right: 파일명 패턴 추출
# ================================================

def test_extract_date_from_IMG_pattern(test_db):
    """6.1 Right: IMG_20230415_123045.jpg → 2023-04-15 12:30:45"""
    extractor = MetadataExtractor(test_db)
    filename = "IMG_20230415_123045.jpg"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15, 12, 30, 45)


def test_extract_date_from_kakao(test_db):
    """6.2 Right: KakaoTalk_20230415_123045.jpg"""
    extractor = MetadataExtractor(test_db)
    filename = "KakaoTalk_20230415_123045.jpg"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15, 12, 30, 45)


def test_extract_date_from_screenshot(test_db):
    """6.3 Right: Screenshot_2023-04-15-12-30-45.png"""
    extractor = MetadataExtractor(test_db)
    filename = "Screenshot_2023-04-15-12-30-45.png"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15, 12, 30, 45)


def test_extract_date_from_whatsapp(test_db):
    """6.4 Right: IMG-20230415-WA0001.jpg"""
    extractor = MetadataExtractor(test_db)
    filename = "IMG-20230415-WA0001.jpg"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15)


def test_extract_date_from_samsung(test_db):
    """6.5 Right: 20230415_123045.jpg"""
    extractor = MetadataExtractor(test_db)
    filename = "20230415_123045.jpg"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15, 12, 30, 45)


def test_extract_date_korean_screenshot(test_db):
    """6.6 Right: 스크린샷 2023-04-15.png"""
    extractor = MetadataExtractor(test_db)
    filename = "스크린샷 2023-04-15.png"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is not None
    assert date == datetime(2023, 4, 15)


# ================================================
# Right: EXIF 추출 및 우선순위
# ================================================

def test_extract_exif_datetime_original(test_db, sample_jpg):
    """6.7 Right: EXIF DateTimeOriginal 읽기"""
    extractor = MetadataExtractor(test_db)

    original, digitized = extractor._extract_exif_dates(sample_jpg)

    # sample_jpg fixture는 DateTimeOriginal을 포함함
    assert original is not None
    assert original == datetime(2023, 4, 15, 12, 30, 45)


def test_extract_exif_datetime_digitized(test_db, tmp_path):
    """6.8 Right: EXIF DateTimeDigitized 읽기"""
    from PIL import Image
    import piexif

    # DateTimeDigitized만 있는 이미지 생성
    img = Image.new("RGB", (100, 100), color="blue")
    exif_dict = {
        "Exif": {
            piexif.ExifIFD.DateTimeDigitized: b"2023:05:20 14:20:30"
        }
    }
    exif_bytes = piexif.dump(exif_dict)

    path = tmp_path / "digitized_only.jpg"
    img.save(str(path), exif=exif_bytes)

    extractor = MetadataExtractor(test_db)
    original, digitized = extractor._extract_exif_dates(path)

    assert original is None
    assert digitized == datetime(2023, 5, 20, 14, 20, 30)


def test_trust_priority_order(test_db):
    """6.9 Right: filename > exif_original > exif_digitized > unknown"""
    extractor = MetadataExtractor(test_db)

    # Case 1: filename만 있음
    date, source, trust = extractor._resolve_date_priority(
        datetime(2023, 1, 1), None, None
    )
    assert source == "filename"
    assert trust == "filename"

    # Case 2: exif_original만 있음
    date, source, trust = extractor._resolve_date_priority(
        None, datetime(2023, 2, 1), None
    )
    assert source == "exif_original"
    assert trust == "exif_original"

    # Case 3: exif_digitized만 있음
    date, source, trust = extractor._resolve_date_priority(
        None, None, datetime(2023, 3, 1)
    )
    assert source == "exif_digitized"
    assert trust == "exif_digitized"

    # Case 4: 모두 있음 → filename 우선
    date, source, trust = extractor._resolve_date_priority(
        datetime(2023, 1, 1),
        datetime(2023, 2, 1),
        datetime(2023, 3, 1)
    )
    assert date == datetime(2023, 1, 1)
    assert source == "filename"

    # Case 5: 없음
    date, source, trust = extractor._resolve_date_priority(None, None, None)
    assert date is None
    assert source == "unknown"
    assert trust == "unknown"


def test_parse_exif_standard_format(test_db):
    """6.10 Right: "2023:04:15 12:30:45" 파싱"""
    extractor = MetadataExtractor(test_db)
    exif_str = "2023:04:15 12:30:45"

    parsed = extractor._parse_exif_datetime(exif_str)

    assert parsed == datetime(2023, 4, 15, 12, 30, 45)


# ================================================
# Boundary: 경계 조건
# ================================================

def test_no_date_in_filename(test_db):
    """6.11 Boundary: 날짜 없는 파일명 → None"""
    extractor = MetadataExtractor(test_db)
    filename = "my_photo.jpg"

    date, pattern = extractor._extract_date_from_filename(filename)

    assert date is None
    assert pattern is None


def test_no_exif_data(test_db, sample_png):
    """6.12 Boundary: EXIF 없는 PNG → None"""
    extractor = MetadataExtractor(test_db)

    original, digitized = extractor._extract_exif_dates(sample_png)

    assert original is None
    assert digitized is None


def test_date_conflict_detection_30_days(test_db):
    """6.13 Boundary: 파일명/EXIF 30일 초과 차이 감지"""
    extractor = MetadataExtractor(test_db)

    filename_date = datetime(2023, 1, 1)
    exif_date = datetime(2023, 2, 5)  # 35일 차이

    conflict = extractor._detect_date_conflict(filename_date, exif_date, threshold_days=30)

    assert conflict is True


def test_date_conflict_boundary_29_days(test_db):
    """6.14 Boundary: 29일 차이 → 충돌 아님"""
    extractor = MetadataExtractor(test_db)

    filename_date = datetime(2023, 1, 1)
    exif_date = datetime(2023, 1, 30)  # 29일 차이

    conflict = extractor._detect_date_conflict(filename_date, exif_date, threshold_days=30)

    assert conflict is False


def test_date_conflict_boundary_31_days(test_db):
    """6.15 Boundary: 31일 차이 → 충돌"""
    extractor = MetadataExtractor(test_db)

    filename_date = datetime(2023, 1, 1)
    exif_date = datetime(2023, 2, 1)  # 31일 차이

    conflict = extractor._detect_date_conflict(filename_date, exif_date, threshold_days=30)

    assert conflict is True


# ================================================
# Error: 예외 처리
# ================================================

def test_corrupted_image_exif(test_db, tmp_path):
    """6.16 Error: 손상된 이미지 → 에러 없이 None"""
    # 손상된 이미지 파일 생성
    corrupted_file = tmp_path / "corrupted.jpg"
    with open(corrupted_file, "wb") as f:
        f.write(b"not a valid image")

    extractor = MetadataExtractor(test_db)

    # 예외 발생 없이 None 반환해야 함
    original, digitized = extractor._extract_exif_dates(corrupted_file)

    assert original is None
    assert digitized is None


def test_invalid_exif_date_format(test_db):
    """6.17 Error: "invalid" → None"""
    extractor = MetadataExtractor(test_db)

    parsed = extractor._parse_exif_datetime("invalid date format")

    assert parsed is None


# ================================================
# Inverse: DB 저장/조회 검증
# ================================================

def test_extract_and_save_to_db(test_db, sample_jpg):
    """6.18 Inverse: 추출 → DB 저장 → DB 조회 일치"""
    # file_classifications 레코드 생성
    test_db.execute(text("""
        INSERT INTO file_classifications (file_path, file_hash, status)
        VALUES (:path, 'hash123', 'pending')
    """), {"path": str(sample_jpg)})
    test_db.commit()

    # 파일 ID 조회
    file_id = test_db.execute(text("""
        SELECT id FROM file_classifications WHERE file_path = :path
    """), {"path": str(sample_jpg)}).fetchone()[0]

    # 메타데이터 추출 및 저장
    extractor = MetadataExtractor(test_db)
    extractor.extract_and_save(file_id, sample_jpg)

    # DB에서 조회
    result = test_db.execute(text("""
        SELECT extracted_date, date_source, date_trust_level
        FROM file_classifications
        WHERE id = :file_id
    """), {"file_id": file_id}).fetchone()

    # 검증
    assert result.extracted_date is not None
    # sample_jpg는 파일명(IMG_20230415_123045.jpg)과 EXIF를 모두 포함하므로
    # 우선순위에 따라 filename이 선택됨
    assert result.date_source == "filename"
    assert result.date_trust_level == "filename"


# ================================================
# Cross-check: 우선순위 조합 테스트
# ================================================

@pytest.mark.parametrize("filename,exif_orig,exif_digi,expected_source", [
    (datetime(2023, 1, 1), datetime(2023, 2, 1), datetime(2023, 3, 1), "filename"),
    (datetime(2023, 1, 1), datetime(2023, 2, 1), None, "filename"),
    (datetime(2023, 1, 1), None, datetime(2023, 3, 1), "filename"),
    (datetime(2023, 1, 1), None, None, "filename"),
    (None, datetime(2023, 2, 1), datetime(2023, 3, 1), "exif_original"),
    (None, datetime(2023, 2, 1), None, "exif_original"),
    (None, None, datetime(2023, 3, 1), "exif_digitized"),
    (None, None, None, "unknown"),
])
def test_all_8_priority_combinations(test_db, filename, exif_orig, exif_digi, expected_source):
    """6.19 Cross-check: filename/exif_original/exif_digitized 조합 8가지"""
    extractor = MetadataExtractor(test_db)

    date, source, trust = extractor._resolve_date_priority(filename, exif_orig, exif_digi)

    assert source == expected_source
