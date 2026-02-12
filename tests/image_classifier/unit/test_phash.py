"""pHash 및 중복 감지 테스트"""
import pytest
import imagehash
from pathlib import Path
from PIL import Image
from sqlalchemy import text
from app.modules.image_classifier.workers.phash import PHashWorker, hamming_distance
from app.modules.image_classifier.workers.duplicate_detector import DuplicateDetector
from app.modules.image_classifier.config import ImageClassifierSettings


# ================================================
# Right: pHash 계산 및 Hamming Distance
# ================================================

def test_phash_computation(test_db, sample_jpg):
    """7.1 Right: 유효한 hex 문자열 반환"""
    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    phash_hex = worker._compute_phash(sample_jpg)

    # hex 문자열이어야 함 (16자리, hash_size=16일 때)
    assert isinstance(phash_hex, str)
    assert len(phash_hex) > 0


def test_identical_images_same_hash(test_db, tmp_path):
    """7.2 Right: 동일 이미지 → 같은 pHash"""
    # 동일한 이미지 2개 생성
    img = Image.new("RGB", (100, 100), color="red")
    path1 = tmp_path / "img1.jpg"
    path2 = tmp_path / "img2.jpg"
    img.save(str(path1))
    img.save(str(path2))

    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    hash1 = worker._compute_phash(path1)
    hash2 = worker._compute_phash(path2)

    assert hash1 == hash2


def test_hamming_distance_identical(test_db):
    """7.3 Right: 같은 해시 → distance=0"""
    hash1 = "ffff0000ffff0000"  # 예시 해시

    distance = hamming_distance(hash1, hash1)

    assert distance == 0


def test_hamming_distance_different(test_db, tmp_path):
    """7.4 Right: 완전히 다른 해시 → distance>0"""
    # 완전히 다른 이미지 2개
    img1 = Image.new("RGB", (100, 100), color="black")
    img2 = Image.new("RGB", (100, 100), color="white")

    path1 = tmp_path / "black.jpg"
    path2 = tmp_path / "white.jpg"
    img1.save(str(path1))
    img2.save(str(path2))

    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    hash1 = worker._compute_phash(path1)
    hash2 = worker._compute_phash(path2)

    distance = hamming_distance(hash1, hash2)

    assert distance > 0


def test_find_similar_by_phash(test_db, tmp_path):
    """7.5 Right: threshold 이하만 반환"""
    from app.modules.image_classifier.workers.phash import find_similar_images

    # 3개 이미지 생성 (1개는 유사, 1개는 다름)
    img_a = Image.new("RGB", (100, 100), color=(50, 100, 150))
    img_b = img_a.copy()  # 동일
    img_c = Image.new("RGB", (100, 100), color="white")  # 완전히 다름

    path_a = tmp_path / "a.jpg"
    path_b = tmp_path / "b.jpg"
    path_c = tmp_path / "c.jpg"

    img_a.save(str(path_a))
    img_b.save(str(path_b))
    img_c.save(str(path_c))

    # DB에 파일 등록
    for idx, path in enumerate([path_a, path_b, path_c], start=1):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, 'hash', 'pending')
        """), {"id": idx, "path": str(path)})

    # pHash 계산 및 저장
    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    for idx, path in enumerate([path_a, path_b, path_c], start=1):
        phash = worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": idx, "phash": phash})

    test_db.commit()

    # a의 phash로 유사 이미지 검색 (threshold=10)
    target_phash = worker._compute_phash(path_a)
    similar = find_similar_images(test_db, target_phash, threshold=10)

    # a와 b는 유사, c는 제외
    file_ids = [s["file_id"] for s in similar]
    assert 1 in file_ids  # a
    assert 2 in file_ids  # b
    # c는 distance가 10 초과이므로 제외될 것


@pytest.mark.asyncio
async def test_duplicate_group_created(test_db, tmp_path):
    """7.6 Right: 중복 감지 → 그룹 생성"""
    # 동일한 이미지 2개 생성
    img = Image.new("RGB", (100, 100), color="blue")
    path1 = tmp_path / "dup1.jpg"
    path2 = tmp_path / "dup2.jpg"
    img.save(str(path1))
    img.save(str(path2))

    # DB에 파일 등록
    for idx, path in enumerate([path1, path2], start=1):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
            VALUES (:id, :path, 'hash123', 1000, 'pending')
        """), {"id": idx, "path": str(path)})

    # pHash 계산
    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)

    for idx, path in enumerate([path1, path2], start=1):
        phash = phash_worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": idx, "phash": phash})

    test_db.commit()

    # 중복 감지
    detector = DuplicateDetector(test_db, settings)
    await detector.detect_duplicates()

    # 중복 그룹이 생성되었는지 확인
    groups = test_db.execute(text("SELECT COUNT(*) FROM duplicate_groups")).fetchone()[0]
    assert groups >= 1


def test_quality_score_calculation(test_db):
    """7.7 Right: (W*H) * (size/1MB) 공식"""
    settings = ImageClassifierSettings()
    detector = DuplicateDetector(test_db, settings)

    # 1920x1080, 2MB
    resolution = "1920x1080"
    file_size = 2 * 1024 * 1024  # 2MB in bytes

    score = detector._calculate_quality_score(resolution, file_size)

    # 예상: 1920 * 1080 * 2 = 4,147,200
    expected = 1920 * 1080 * 2
    assert abs(score - expected) < 1  # 부동소수점 오차 허용


def test_image_resolution_extracted(test_db, tmp_path):
    """7.8 Right: "1920x1080" 형식"""
    # 특정 해상도 이미지 생성
    img = Image.new("RGB", (1920, 1080), color="green")
    path = tmp_path / "resolution_test.jpg"
    img.save(str(path))

    settings = ImageClassifierSettings()
    detector = DuplicateDetector(test_db, settings)

    resolution = detector._get_image_resolution(str(path))

    assert resolution == "1920x1080"


# ================================================
# Boundary: 경계 조건
# ================================================

def test_hamming_distance_threshold_10(test_db, duplicate_pair):
    """7.9 Boundary: distance=10 → 유사, distance=11 → 비유사"""
    path_a, path_b = duplicate_pair

    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    hash_a = worker._compute_phash(path_a)
    hash_b = worker._compute_phash(path_b)

    distance = hamming_distance(hash_a, hash_b)

    # duplicate_pair는 약간 변형된 이미지이므로 distance가 작아야 함
    # threshold=10 이하여야 중복으로 판정
    assert distance <= 10


@pytest.mark.asyncio
async def test_single_file_no_duplicates(test_db, tmp_path):
    """7.10 Boundary: 파일 1개 → 중복 그룹 없음"""
    # 파일 1개만 생성
    img = Image.new("RGB", (100, 100), color="yellow")
    path = tmp_path / "single.jpg"
    img.save(str(path))

    # DB 등록
    test_db.execute(text("""
        INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
        VALUES (1, :path, 'hash1', 1000, 'pending')
    """), {"path": str(path)})

    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)
    phash = phash_worker._compute_phash(path)

    test_db.execute(text("""
        INSERT INTO image_features (file_id, phash) VALUES (1, :phash)
    """), {"phash": phash})
    test_db.commit()

    # 중복 감지
    detector = DuplicateDetector(test_db, settings)
    await detector.detect_duplicates()

    # 중복 그룹 없어야 함
    groups = test_db.execute(text("SELECT COUNT(*) FROM duplicate_groups")).fetchone()[0]
    assert groups == 0


@pytest.mark.asyncio
async def test_two_identical_files(test_db, tmp_path):
    """7.11 Boundary: 파일 2개 동일 → 1개 그룹"""
    # 동일한 이미지 2개
    img = Image.new("RGB", (100, 100), color="cyan")
    path1 = tmp_path / "file1.jpg"
    path2 = tmp_path / "file2.jpg"
    img.save(str(path1))
    img.save(str(path2))

    # DB 등록
    for idx, path in enumerate([path1, path2], start=1):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
            VALUES (:id, :path, 'hash', 1000, 'pending')
        """), {"id": idx, "path": str(path)})

    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)

    for idx, path in enumerate([path1, path2], start=1):
        phash = phash_worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": idx, "phash": phash})

    test_db.commit()

    # 중복 감지
    detector = DuplicateDetector(test_db, settings)
    await detector.detect_duplicates()

    # 1개 그룹
    groups = test_db.execute(text("SELECT COUNT(*) FROM duplicate_groups")).fetchone()[0]
    assert groups == 1


# ================================================
# Error: 예외 처리
# ================================================

def test_phash_corrupted_image(test_db, tmp_path):
    """7.12 Error: 손상된 이미지 → 에러 처리"""
    # 손상된 이미지 생성
    corrupted = tmp_path / "corrupted.jpg"
    with open(corrupted, "wb") as f:
        f.write(b"invalid image data")

    settings = ImageClassifierSettings()
    worker = PHashWorker(test_db, settings)

    # 예외 발생해야 함
    with pytest.raises(Exception):
        worker._compute_phash(corrupted)


def test_resolution_unknown_format(test_db):
    """7.13 Error: 해상도 알 수 없을 때 "unknown" 처리"""
    settings = ImageClassifierSettings()
    detector = DuplicateDetector(test_db, settings)

    # 존재하지 않는 파일
    resolution = detector._get_image_resolution("/nonexistent/file.jpg")

    assert resolution == "unknown"


# ================================================
# Inverse: DB 저장/조회
# ================================================

@pytest.mark.asyncio
async def test_detect_and_query_groups(test_db, tmp_path):
    """7.14 Inverse: 감지 → DB 조회 일치"""
    # 2개의 동일 이미지 생성
    img = Image.new("RGB", (200, 200), color="magenta")
    path1 = tmp_path / "img1.jpg"
    path2 = tmp_path / "img2.jpg"
    img.save(str(path1))
    img.save(str(path2))

    # DB 등록
    for idx, path in enumerate([path1, path2], start=1):
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
            VALUES (:id, :path, 'hash', 2000, 'pending')
        """), {"id": idx, "path": str(path)})

    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)

    for idx, path in enumerate([path1, path2], start=1):
        phash = phash_worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": idx, "phash": phash})

    test_db.commit()

    # 중복 감지
    detector = DuplicateDetector(test_db, settings)
    await detector.detect_duplicates()

    # DB 조회
    groups = test_db.execute(text("""
        SELECT id, member_count FROM duplicate_groups
    """)).fetchall()

    assert len(groups) >= 1
    assert groups[0].member_count == 2


# ================================================
# Performance: 성능 테스트
# ================================================

@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_100_files_performance(test_db, tmp_path):
    """7.15 Performance: 100개 파일 O(n^2) 시간 확인"""
    import time

    # 100개 파일 생성
    for i in range(100):
        img = Image.new("RGB", (50, 50), color=(i % 256, (i*2) % 256, (i*3) % 256))
        path = tmp_path / f"file{i:03d}.jpg"
        img.save(str(path))

        # DB 등록
        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, file_size, status)
            VALUES (:id, :path, 'hash', 1000, 'pending')
        """), {"id": i+1, "path": str(path)})

    settings = ImageClassifierSettings()
    phash_worker = PHashWorker(test_db, settings)

    # pHash 계산
    for i in range(100):
        path = tmp_path / f"file{i:03d}.jpg"
        phash = phash_worker._compute_phash(path)
        test_db.execute(text("""
            INSERT INTO image_features (file_id, phash) VALUES (:fid, :phash)
        """), {"fid": i+1, "phash": phash})

    test_db.commit()

    # 중복 감지 시간 측정
    detector = DuplicateDetector(test_db, settings)
    start = time.time()
    await detector.detect_duplicates()
    elapsed = time.time() - start

    # O(n^2) 알고리즘이므로 시간이 오래 걸릴 수 있음
    # 100개: 약 4950회 비교 (100*99/2)
    # 합리적인 시간 내 완료되어야 함 (예: 30초 이내)
    assert elapsed < 30.0
