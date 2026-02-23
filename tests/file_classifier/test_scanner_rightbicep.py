"""
Scanner RIGHT-BICEP TC
R: 결과 정확성
B/CORRECT: 경계값
I: 역관계
C: 교차검증
E: 오류 조건
P: 성능
"""
import pytest
import time
from pathlib import Path
from unittest.mock import patch
from app.modules.file_classifier.workers.scanner import FileScanner, get_file_group, FILE_GROUP_MAP

class TestScannerRight:
    """R: 결과 정확성"""
    def test_file_group_assigned_correctly(self, tmp_path, test_db):
        """정상 스캔 시 file_group 정확히 매핑"""
        from sqlalchemy import text as sqla_text

        # 별도 서브디렉토리에 테스트 파일 생성 (tmp_path 루트에 있는 DB 파일 등 제외)
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        files = {
            "song.mp3": "music",
            "video.mp4": "video",
            "photo.jpg": "image",
            "archive.zip": "archive",
            "doc.pdf": "document",
            "setup.exe": "installer",
            "track.dtx": "game",
            "unknown.xyz": "misc",
        }
        for fname in files:
            (scan_dir / fname).write_bytes(b"test")

        scanner = FileScanner(test_db)
        result = scanner.scan([str(scan_dir)])

        assert result["inserted"] == len(files)

        rows = test_db.execute(sqla_text("SELECT file_name, file_group FROM fc_files")).fetchall()
        actual = {row[0]: row[1] for row in rows}
        for fname, expected_group in files.items():
            assert actual.get(fname) == expected_group, f"{fname}: 기대 {expected_group}, 실제 {actual.get(fname)}"

class TestScannerBoundaryCorrect:
    """B/CORRECT: 경계값"""

    def test_zero_byte_file(self, tmp_path, test_db):
        """0바이트 파일도 스캔 성공"""
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_zero"
        scan_dir.mkdir()
        (scan_dir / "empty.txt").write_bytes(b"")

        scanner = FileScanner(test_db)
        result = scanner.scan([str(scan_dir)])
        assert result["inserted"] == 1
        row = test_db.execute(text("SELECT file_size FROM fc_files WHERE file_name='empty.txt'")).fetchone()
        assert row[0] == 0

    def test_long_filename(self, tmp_path, test_db):
        """긴 파일명 처리 (200자)"""
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_long"
        scan_dir.mkdir()
        long_name = "a" * 196 + ".txt"
        (scan_dir / long_name).write_bytes(b"test")

        scanner = FileScanner(test_db)
        result = scanner.scan([str(scan_dir)])
        assert result["errors"] == 0
        assert result["inserted"] == 1

    def test_extension_case_insensitive(self, tmp_path, test_db):
        """확장자 대소문자 무관"""
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_case"
        scan_dir.mkdir()
        (scan_dir / "SONG.MP3").write_bytes(b"test")
        (scan_dir / "Video.Mp4").write_bytes(b"test")

        scanner = FileScanner(test_db)
        scanner.scan([str(scan_dir)])
        rows = test_db.execute(text("SELECT file_name, file_group FROM fc_files")).fetchall()
        groups = {r[0]: r[1] for r in rows}
        assert groups.get("SONG.MP3") == "music"
        assert groups.get("Video.Mp4") == "video"

    def test_nonexistent_folder_skipped(self, test_db):
        """존재하지 않는 폴더 → 오류 없이 0건"""
        scanner = FileScanner(test_db)
        result = scanner.scan(["/nonexistent/path/xyz"])
        assert result["inserted"] == 0
        assert result["errors"] == 0

    def test_max_files_limit(self, tmp_path, test_db):
        """MAX_FILES_PER_SCAN 한도 준수"""
        from sqlalchemy import text
        from app.modules.file_classifier import config as fc_config

        # 10개 파일 생성, 한도 5로 설정
        scan_dir = tmp_path / "scan_max"
        scan_dir.mkdir()
        for i in range(10):
            (scan_dir / f"file{i:02d}.txt").write_bytes(b"test")

        original = fc_config.settings.MAX_FILES_PER_SCAN
        fc_config.settings.MAX_FILES_PER_SCAN = 5
        try:
            scanner = FileScanner(test_db)
            result = scanner.scan([str(scan_dir)])
            count = test_db.execute(text("SELECT COUNT(*) FROM fc_files")).scalar()
            assert count <= 5
        finally:
            fc_config.settings.MAX_FILES_PER_SCAN = original

    def test_duplicate_scan_no_duplicate_rows(self, tmp_path, test_db):
        """같은 경로 2회 스캔 → DB 중복 없음 (CORRECT-Ordering)"""
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_dup"
        scan_dir.mkdir()
        (scan_dir / "dup.txt").write_bytes(b"test")

        scanner = FileScanner(test_db)
        scanner.scan([str(scan_dir)])
        scanner.scan([str(scan_dir)])  # 2회
        count = test_db.execute(text("SELECT COUNT(*) FROM fc_files")).scalar()
        assert count == 1  # INSERT OR IGNORE

class TestScannerInverse:
    """I: 역관계 - 스캔 결과 DB 반영 일치"""
    def test_inserted_count_matches_db(self, tmp_path, test_db):
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_inv"
        scan_dir.mkdir()
        for i in range(5):
            (scan_dir / f"f{i}.txt").write_bytes(b"x")

        scanner = FileScanner(test_db)
        result = scanner.scan([str(scan_dir)])
        db_count = test_db.execute(text("SELECT COUNT(*) FROM fc_files")).scalar()
        assert result["inserted"] == db_count

class TestScannerCrossCheck:
    """C: 교차검증 - 통계 일관성"""
    def test_group_stats_sum_equals_total(self, tmp_path, test_db):
        """file_group별 합계 == 전체 파일 수"""
        from sqlalchemy import text
        scan_dir = tmp_path / "scan_cross"
        scan_dir.mkdir()
        files = ["a.mp3", "b.mp4", "c.jpg", "d.zip", "e.pdf", "f.exe", "g.dtx", "h.xyz"]
        for f in files:
            (scan_dir / f).write_bytes(b"x")

        scanner = FileScanner(test_db)
        scanner.scan([str(scan_dir)])

        total = test_db.execute(text("SELECT COUNT(*) FROM fc_files")).scalar()
        group_sum = test_db.execute(text(
            "SELECT SUM(cnt) FROM (SELECT COUNT(*) as cnt FROM fc_files GROUP BY file_group)"
        )).scalar()
        assert total == group_sum == len(files)

class TestScannerError:
    """E: 오류 조건"""
    def test_permission_error_folder_skipped(self, tmp_path, test_db):
        """PermissionError 폴더 → 스킵, 전체 중단 없음"""
        import os

        # 정상 파일
        scan_dir = tmp_path / "scan_err"
        scan_dir.mkdir()
        (scan_dir / "ok.txt").write_bytes(b"x")

        scanner = FileScanner(test_db)
        # os.scandir에 PermissionError 시뮬레이션
        original_scandir = os.scandir
        call_count = [0]
        def patched_scandir(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise PermissionError("Access denied")
            return original_scandir(path)

        with patch("app.modules.file_classifier.workers.scanner.os.scandir", patched_scandir):
            result = scanner.scan([str(scan_dir)])
        # PermissionError → 0 inserted, 0 errors (스킵)
        assert result["errors"] == 0

class TestScannerPerformance:
    """P: 성능"""
    def test_100_files_under_5_seconds(self, tmp_path, test_db):
        """100개 파일 스캔 < 5초"""
        scan_dir = tmp_path / "scan_perf"
        scan_dir.mkdir()
        for i in range(100):
            (scan_dir / f"perf_{i:03d}.txt").write_bytes(b"x")

        scanner = FileScanner(test_db)
        start = time.time()
        scanner.scan([str(scan_dir)])
        elapsed = time.time() - start
        assert elapsed < 5.0, f"100개 스캔에 {elapsed:.2f}초 소요 (한도: 5초)"
