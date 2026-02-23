"""압축 파일 메타데이터 추출 테스트"""
import pytest
import zipfile
import tempfile
import os
from pathlib import Path
from sqlalchemy import text


def _create_test_zip(tmp_path: Path, files: dict) -> Path:
    """테스트용 ZIP 파일 생성"""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return zip_path


def test_extract_zip(test_db, tmp_path):
    """ZIP 파일 내용 추출 테스트"""
    from app.modules.file_classifier.workers.metadata.archive import extract

    zip_path = _create_test_zip(tmp_path, {
        "file1.txt": "hello",
        "subdir/file2.py": "print('world')",
    })

    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group) "
        "VALUES (200, :path, 'test.zip', '.zip', 1024, 'archive')"
    ), {"path": str(zip_path)})
    test_db.commit()

    result = extract(200, str(zip_path), test_db)

    assert result["file_count"] == 2
    assert result["is_encrypted"] is False

    # fc_archive_contents에 기록됐는지 확인
    rows = test_db.execute(text(
        "SELECT COUNT(*) FROM fc_archive_contents WHERE file_id = 200"
    )).fetchone()
    assert rows[0] >= 2


def test_extract_nonexistent(test_db):
    """존재하지 않는 파일 처리"""
    from app.modules.file_classifier.workers.metadata.archive import extract
    result = extract(999, "/nonexistent/archive.zip", test_db)
    # 에러가 있어도 크래시 없이 처리
    assert isinstance(result, dict)


def test_extract_empty_zip(test_db, tmp_path):
    """빈 ZIP 파일"""
    from app.modules.file_classifier.workers.metadata.archive import extract

    zip_path = _create_test_zip(tmp_path, {})
    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group) "
        "VALUES (201, :path, 'empty.zip', '.zip', 22, 'archive')"
    ), {"path": str(zip_path)})
    test_db.commit()

    result = extract(201, str(zip_path), test_db)
    assert result["file_count"] == 0
