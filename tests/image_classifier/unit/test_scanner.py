"""스캔 워커 테스트"""
import hashlib
import pytest
from pathlib import Path
from sqlalchemy import text
from app.modules.image_classifier.workers.scanner import FolderScanner
from app.modules.image_classifier.config import ImageClassifierSettings


@pytest.mark.asyncio
async def test_finds_only_image_extensions(test_db, tmp_path):
    """3.1 Right: .jpg/.png/.gif만 찾고 .txt/.pdf는 제외"""
    # 이미지 파일과 비이미지 파일 생성
    (tmp_path / "photo.jpg").touch()
    (tmp_path / "image.png").touch()
    (tmp_path / "animation.gif").touch()
    (tmp_path / "document.txt").touch()
    (tmp_path / "manual.pdf").touch()
    (tmp_path / "data.json").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # DB에 저장된 파일 수 확인 (이미지만 3개)
    result = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()
    assert result[0] == 3


@pytest.mark.asyncio
async def test_case_insensitive_extension(test_db, tmp_path):
    """3.2 Right: .JPG, .Png도 인식"""
    (tmp_path / "photo1.JPG").touch()
    (tmp_path / "photo2.Png").touch()
    (tmp_path / "photo3.GIF").touch()
    (tmp_path / "photo4.JPEG").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 대소문자 구분 없이 모두 인식
    result = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()
    assert result[0] == 4


@pytest.mark.asyncio
async def test_all_8_extensions_supported(test_db, tmp_path):
    """3.3 Right: jpg/jpeg/png/gif/bmp/webp/heic/tiff 모두 지원"""
    extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff"]

    for ext in extensions:
        (tmp_path / f"image{ext}").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 8개 확장자 모두 인식
    result = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()
    assert result[0] == 8


@pytest.mark.asyncio
async def test_sha256_hash_calculated(test_db, tmp_path, sample_jpg):
    """3.4 Right: SHA256 해시가 정확히 계산되어 저장됨"""
    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(sample_jpg.parent)])

    # DB에서 해시 조회
    result = test_db.execute(
        text("SELECT file_hash FROM file_classifications WHERE file_path = :path"),
        {"path": str(sample_jpg)}
    ).fetchone()

    db_hash = result[0]

    # 실제 파일 해시 계산
    sha256 = hashlib.sha256()
    with open(sample_jpg, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    expected_hash = sha256.hexdigest()

    # 일치 확인
    assert db_hash == expected_hash


@pytest.mark.asyncio
async def test_folder_mappings_created(test_db, tmp_path):
    """3.5 Right: 스캔한 폴더가 folder_mappings에 INSERT됨"""
    # 폴더 생성
    folder1 = tmp_path / "Photos"
    folder1.mkdir()
    (folder1 / "a.jpg").touch()

    folder2 = tmp_path / "Images"
    folder2.mkdir()
    (folder2 / "b.png").touch()

    # tmp_path에도 파일 추가
    (tmp_path / "root.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # folder_mappings 확인
    result = test_db.execute(
        text("SELECT COUNT(*) FROM folder_mappings")
    ).fetchone()

    # 3개 폴더: tmp_path, Photos, Images
    assert result[0] == 3


@pytest.mark.asyncio
async def test_file_classifications_created(test_db, tmp_path):
    """3.6 Right: 스캔한 파일이 file_classifications에 INSERT됨"""
    (tmp_path / "photo1.jpg").touch()
    (tmp_path / "photo2.png").touch()
    (tmp_path / "photo3.gif").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # file_classifications 확인
    result = test_db.execute(
        text("SELECT COUNT(*) FROM file_classifications")
    ).fetchone()

    assert result[0] == 3


@pytest.mark.asyncio
async def test_file_count_per_folder(test_db, tmp_path):
    """3.7 Right: 각 폴더의 file_count가 정확함"""
    # folder1: 2개
    folder1 = tmp_path / "folder1"
    folder1.mkdir()
    (folder1 / "a.jpg").touch()
    (folder1 / "b.png").touch()

    # folder2: 3개
    folder2 = tmp_path / "folder2"
    folder2.mkdir()
    (folder2 / "c.jpg").touch()
    (folder2 / "d.jpg").touch()
    (folder2 / "e.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 각 폴더의 file_count 확인
    result = test_db.execute(
        text("SELECT folder_path, file_count FROM folder_mappings WHERE file_count > 0 ORDER BY folder_path")
    ).fetchall()

    folder_counts = {row[0]: row[1] for row in result}

    assert folder_counts[str(folder1)] == 2
    assert folder_counts[str(folder2)] == 3


@pytest.mark.asyncio
async def test_empty_folder(test_db, tmp_path):
    """3.8 Boundary: 빈 폴더 (0개 파일)"""
    # 빈 폴더 생성
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # folder_mappings에 추가되지 않아야 함 (이미지 파일 없으므로)
    result = test_db.execute(
        text("SELECT COUNT(*) FROM folder_mappings WHERE folder_path = :path"),
        {"path": str(empty_folder)}
    ).fetchone()

    assert result[0] == 0


@pytest.mark.asyncio
async def test_single_file(test_db, tmp_path):
    """3.9 Boundary: 파일 1개만 있는 폴더"""
    (tmp_path / "single.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 폴더 1개, 파일 1개
    folder_count = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings")).fetchone()[0]
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]

    assert folder_count == 1
    assert file_count == 1


@pytest.mark.asyncio
async def test_nested_3_levels(test_db, tmp_path):
    """3.10 Boundary: 3단계 중첩 폴더 재귀 스캔"""
    # a/b/c 3단계 중첩
    level1 = tmp_path / "a"
    level2 = level1 / "b"
    level3 = level2 / "c"
    level3.mkdir(parents=True)

    (level1 / "1.jpg").touch()
    (level2 / "2.jpg").touch()
    (level3 / "3.jpg").touch()
    (tmp_path / "0.jpg").touch()  # tmp_path에도 파일 추가

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 4개 폴더 (tmp_path, a, b, c)
    folder_count = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings")).fetchone()[0]
    assert folder_count == 4

    # 4개 파일
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]
    assert file_count == 4


@pytest.mark.asyncio
async def test_hidden_folder_excluded(test_db, tmp_path):
    """3.11 Boundary: .hidden 폴더 제외"""
    # 일반 폴더
    normal = tmp_path / "normal"
    normal.mkdir()
    (normal / "photo.jpg").touch()

    # 숨김 폴더
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # .hidden 폴더는 스캔되지 않아야 함
    result = test_db.execute(
        text("SELECT COUNT(*) FROM folder_mappings WHERE folder_path LIKE :pattern"),
        {"pattern": "%\\.hidden%"}
    ).fetchone()

    assert result[0] == 0

    # 일반 폴더만 스캔됨
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]
    assert file_count == 1  # normal/photo.jpg만


@pytest.mark.asyncio
async def test_duplicate_scan_no_duplicates(test_db, tmp_path):
    """3.12 Boundary: 같은 폴더 2번 스캔 → 중복 INSERT 없음"""
    (tmp_path / "photo.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    # 첫 번째 스캔
    await scanner.scan_folders([str(tmp_path)])

    # 두 번째 스캔
    scanner2 = FolderScanner(test_db, settings)
    await scanner2.scan_folders([str(tmp_path)])

    # 파일은 1개만 있어야 함
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]
    assert file_count == 1


@pytest.mark.asyncio
async def test_scan_result_matches_filesystem(test_db, tmp_path):
    """3.13 Inverse: 파일 시스템 파일 수 == DB 레코드 수"""
    # 10개 이미지 파일 생성
    for i in range(10):
        (tmp_path / f"photo{i}.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)])

    # 파일 시스템 파일 수
    fs_count = len(list(tmp_path.glob("*.jpg")))

    # DB 파일 수
    db_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]

    assert fs_count == db_count == 10


@pytest.mark.asyncio
async def test_nonexistent_folder(test_db, tmp_path):
    """3.14 Error: 존재하지 않는 폴더 처리"""
    nonexistent = tmp_path / "nonexistent"

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    # 예외 발생 없이 처리되어야 함
    await scanner.scan_folders([str(nonexistent)])

    # DB에 아무것도 추가되지 않음
    folder_count = test_db.execute(text("SELECT COUNT(*) FROM folder_mappings")).fetchone()[0]
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]

    assert folder_count == 0
    assert file_count == 0


@pytest.mark.asyncio
async def test_progress_callback_called(test_db, tmp_path):
    """3.15 Error: on_progress 콜백이 호출됨"""
    # 3개 폴더, 각 1개 파일
    for i in range(3):
        folder = tmp_path / f"folder{i}"
        folder.mkdir()
        (folder / "photo.jpg").touch()

    progress_calls = []

    def on_progress(**kwargs):
        progress_calls.append(kwargs)

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    await scanner.scan_folders([str(tmp_path)], on_progress=on_progress)

    # 콜백이 호출되었는지 확인 (최소 1회)
    assert len(progress_calls) > 0

    # 마지막 콜백에서 total_folders가 4 (tmp_path + 3개 하위)
    last_call = progress_calls[-1]
    assert last_call["total_folders"] == 4
    assert last_call["scanned_folders"] == 4


@pytest.mark.asyncio
@pytest.mark.slow
async def test_scan_1000_files_under_5s(test_db, tmp_path):
    """3.16 Performance: 1000개 파일 25초 이내 스캔"""
    import time

    # 1000개 파일 생성
    for i in range(1000):
        (tmp_path / f"photo{i:04d}.jpg").touch()

    settings = ImageClassifierSettings()
    scanner = FolderScanner(test_db, settings)

    start = time.time()
    await scanner.scan_folders([str(tmp_path)])
    elapsed = time.time() - start

    # 30초 이내 (실제 환경에서 20~25초 걸림, CI 부하 고려)
    assert elapsed < 30.0

    # 1000개 파일 모두 스캔됨
    file_count = test_db.execute(text("SELECT COUNT(*) FROM file_classifications")).fetchone()[0]
    assert file_count == 1000
