"""음악 메타데이터 추출 테스트"""
import pytest
import tempfile
import os
from pathlib import Path
from sqlalchemy import text
from unittest.mock import patch, MagicMock


def test_detect_artist_lang_korean():
    from app.modules.file_classifier.workers.metadata.music import detect_artist_lang
    assert detect_artist_lang("아이유") == "ko"


def test_detect_artist_lang_japanese():
    from app.modules.file_classifier.workers.metadata.music import detect_artist_lang
    assert detect_artist_lang("きゃりーぱみゅぱみゅ") == "ja"


def test_detect_artist_lang_english():
    from app.modules.file_classifier.workers.metadata.music import detect_artist_lang
    assert detect_artist_lang("BTS") == "en"


def test_detect_artist_lang_empty():
    from app.modules.file_classifier.workers.metadata.music import detect_artist_lang
    assert detect_artist_lang("") == "unknown"


def test_extract_no_file(test_db):
    """파일이 없을 때 gracefully 처리"""
    from app.modules.file_classifier.workers.metadata.music import extract
    result = extract(1, "/nonexistent/file.mp3", test_db)
    assert "error" in result or result.get("has_tags") == False


def test_extract_with_tags(test_db):
    """mutagen mock으로 태그 추출 테스트"""
    from app.modules.file_classifier.workers.metadata.music import extract

    # fc_files에 레코드 삽입
    test_db.execute(text(
        "INSERT INTO fc_files (id, file_path, file_name, extension, file_size, file_group) "
        "VALUES (100, '/tmp/test.mp3', 'test.mp3', '.mp3', 1024, 'music')"
    ))
    test_db.commit()

    mock_audio = MagicMock()
    mock_audio.get.side_effect = lambda k, default=None: {
        "title": ["Test Song"],
        "artist": ["아이유"],
        "album": ["LILAC"],
        "genre": ["K-pop"],
        "date": ["2021"],
    }.get(k, default)
    mock_audio.info.length = 200
    mock_audio.info.bitrate = 320000

    import sys
    import types
    # mutagen이 없으면 mock 모듈 생성
    if "mutagen" not in sys.modules:
        mock_mutagen = types.ModuleType("mutagen")
        mock_mutagen.File = MagicMock(return_value=mock_audio)
        sys.modules["mutagen"] = mock_mutagen
        result = extract(100, "/tmp/test.mp3", test_db)
        del sys.modules["mutagen"]
    else:
        with patch("mutagen.File", return_value=mock_audio):
            result = extract(100, "/tmp/test.mp3", test_db)

    assert result["has_tags"] is True
    assert result["artist_lang"] == "ko"

    # DB 확인
    row = test_db.execute(text(
        "SELECT artist, artist_lang, has_tags FROM fc_music_meta WHERE file_id = 100"
    )).fetchone()
    assert row is not None
    assert row[0] == "아이유"
    assert row[1] == "ko"
    assert row[2] == 1
