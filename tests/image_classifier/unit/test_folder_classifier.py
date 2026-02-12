"""폴더 분류 로직 테스트"""
import pytest
from pathlib import Path
from sqlalchemy import text
from app.modules.image_classifier.workers.folder_classifier import FolderClassifier


# ================================================
# Right: 명확/불명확/날짜 패턴 인식
# ================================================

@pytest.mark.parametrize("folder_name,expected", [
    ("여행 2023", "clear"),
    ("family_photos", "clear"),
    ("음식 맛집", "clear"),
    ("졸업식", "clear"),
    ("screenshot_2023", "clear"),
])
def test_clear_patterns(test_db, folder_name, expected):
    """4.1-4.5 Right: 명확한 패턴은 clear로 분류"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(folder_name, file_count=10, subfolders=[])
    assert result == expected


@pytest.mark.parametrize("folder_name,expected", [
    ("새 폴더", "unclear"),
    ("new folder 2", "unclear"),
    ("12345", "unclear"),
    ("temp", "unclear"),
    ("기타", "unclear"),
])
def test_unclear_patterns(test_db, folder_name, expected):
    """4.6-4.10 Right: 불명확한 패턴은 unclear로 분류"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(folder_name, file_count=10, subfolders=[])
    assert result == expected


@pytest.mark.parametrize("folder_name,expected", [
    ("20230415", "unclear"),
    ("2023-04-15", "unclear"),
    ("2023.04.15", "unclear"),
])
def test_date_only_patterns(test_db, folder_name, expected):
    """4.11-4.13 Right: 날짜만 있는 패턴은 unclear로 분류"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(folder_name, file_count=10, subfolders=[])
    assert result == expected


def test_flat_detection(test_db):
    """4.14 Right: 파일 500개 + 서브폴더 0개 → flat"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/Photos/flat_folder",
        file_count=500,
        subfolders=[]
    )
    assert result == "flat"


def test_nested_detection(test_db):
    """4.15 Right: depth>5 + 서브폴더 있음 → nested"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/a/b/c/d/e/f",  # depth=7
        file_count=10,
        subfolders=["D:/a/b/c/d/e/f/g"]
    )
    assert result == "nested"


def test_short_name_unclear(test_db):
    """4.16 Right: 2글자 이하 → unclear"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder("ab", file_count=10, subfolders=[])
    assert result == "unclear"


def test_two_words_clear(test_db):
    """4.17 Right: 한글+영문 2단어 → clear"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder("여행 photos", file_count=10, subfolders=[])
    assert result == "clear"


# ================================================
# Boundary: 경계값 테스트
# ================================================

def test_flat_boundary_499(test_db):
    """4.18 Boundary: 499개 파일 → flat 아님"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/Photos/almost_flat",
        file_count=499,
        subfolders=[]
    )
    # 499개는 flat이 아님 (unclear 또는 clear 패턴에 따라)
    assert result != "flat"


def test_flat_boundary_500(test_db):
    """4.19 Boundary: 500개 파일 → flat"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/Photos/flat_boundary",
        file_count=500,
        subfolders=[]
    )
    assert result == "flat"


def test_flat_with_subfolders(test_db):
    """4.20 Boundary: 500개 + 서브폴더 → flat 아님"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/Photos/not_flat",
        file_count=500,
        subfolders=["D:/Photos/not_flat/sub1"]
    )
    # 서브폴더가 있으면 flat이 아님
    assert result != "flat"


def test_nested_depth_5(test_db):
    """4.21 Boundary: depth=5 → nested 아님"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/a/b/c/d",  # depth=5
        file_count=10,
        subfolders=["D:/a/b/c/d/e"]
    )
    # depth > 5가 아니므로 nested 아님
    assert result != "nested"


def test_nested_depth_6(test_db):
    """4.22 Boundary: depth=6 + 서브폴더 → nested"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder(
        folder_path="D:/a/b/c/d/e",  # depth=6
        file_count=10,
        subfolders=["D:/a/b/c/d/e/f"]
    )
    assert result == "nested"


def test_empty_folder_name(test_db):
    """4.23 Boundary: 빈 문자열 → unclear"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder("", file_count=10, subfolders=[])
    assert result == "unclear"


def test_single_char_name(test_db):
    """4.24 Boundary: 1글자 → unclear"""
    classifier = FolderClassifier(test_db)
    result = classifier.classify_folder("a", file_count=10, subfolders=[])
    assert result == "unclear"


# ================================================
# Cross-check: 일관성 검증
# ================================================

def test_classify_consistency_10_times(test_db):
    """4.25 Cross-check: 같은 입력 10번 → 같은 결과"""
    classifier = FolderClassifier(test_db)

    results = []
    for _ in range(10):
        result = classifier.classify_folder("여행 2023", file_count=10, subfolders=[])
        results.append(result)

    # 모든 결과가 동일해야 함
    assert len(set(results)) == 1
    assert results[0] == "clear"


# ================================================
# Inverse: classify_all_folders 검증
# ================================================

def test_classify_all_updates_db(test_db):
    """4.26 Inverse: classify_all_folders() → DB 상태 반영"""
    # 폴더 3개 추가 (folder_status='unknown')
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count, folder_status) VALUES
        ('D:/Photos/여행', 10, 'unknown'),
        ('D:/Photos/새 폴더', 5, 'unknown'),
        ('D:/Photos/flat_folder', 500, 'unknown')
    """))
    test_db.commit()

    classifier = FolderClassifier(test_db)
    result = classifier.classify_all_folders()

    # DB에서 상태 확인
    folders = test_db.execute(text("""
        SELECT folder_path, folder_status FROM folder_mappings ORDER BY folder_path
    """)).fetchall()

    statuses = {row[0]: row[1] for row in folders}

    # 여행 → clear
    assert statuses["D:/Photos/여행"] == "clear"
    # 새 폴더 → unclear
    assert statuses["D:/Photos/새 폴더"] == "unclear"
    # flat_folder (500개 파일, 서브폴더 없음) → flat
    assert statuses["D:/Photos/flat_folder"] == "flat"


def test_classify_all_returns_correct_stats(test_db):
    """4.27 Inverse: 반환 stats와 DB가 일치"""
    # 폴더 5개 추가
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count, folder_status) VALUES
        ('D:/Photos/여행', 10, 'unknown'),
        ('D:/Photos/음식', 8, 'unknown'),
        ('D:/Photos/새 폴더', 5, 'unknown'),
        ('D:/Photos/temp', 3, 'unknown'),
        ('D:/Photos/flat_folder', 500, 'unknown')
    """))
    test_db.commit()

    classifier = FolderClassifier(test_db)
    result = classifier.classify_all_folders()

    # 통계 확인
    assert result["total"] == 5
    assert result["clear"] == 2  # 여행, 음식
    assert result["unclear"] == 2  # 새 폴더, temp
    assert result["flat"] == 1  # flat_folder

    # DB 상태와 일치 확인
    db_clear = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings WHERE folder_status='clear'")).fetchone()[0]
    db_unclear = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings WHERE folder_status='unclear'")).fetchone()[0]
    db_flat = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings WHERE folder_status='flat'")).fetchone()[0]

    assert db_clear == result["clear"]
    assert db_unclear == result["unclear"]
    assert db_flat == result["flat"]


# ================================================
# Error: 예외 조건
# ================================================

def test_classify_all_no_unknown_folders(test_db):
    """4.28 Error: unknown 폴더 없으면 결과 total=0"""
    # 폴더 추가 (이미 분류됨)
    test_db.execute(text("""
        INSERT INTO folder_mappings (folder_path, file_count, folder_status) VALUES
        ('D:/Photos/여행', 10, 'clear'),
        ('D:/Photos/음식', 8, 'clear')
    """))
    test_db.commit()

    classifier = FolderClassifier(test_db)
    result = classifier.classify_all_folders(force=False)  # unknown만 분류

    # unknown 폴더가 없으므로 total=0
    assert result["total"] == 0
    assert result["clear"] == 0
    assert result["unclear"] == 0
    assert result["flat"] == 0
    assert result["nested"] == 0
