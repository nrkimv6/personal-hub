"""
단위 TC: scripts/ci/check_watchdog_placeholders.py

RIGHT-BICEP:
- R: placeholder 패턴 포함 파일 → 감지 (True)
- R: 정상 파일 → 통과 (False)
- B: 빈 파일 → 통과
- E: 파일 없음 디렉토리 → 통과 (0 반환)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ci 경로를 sys.path에 추가
_SCRIPTS_CI = Path(__file__).parent.parent / "scripts" / "ci"
sys.path.insert(0, str(_SCRIPTS_CI))

from check_watchdog_placeholders import check_file, main


class TestCheckFile:
    def test_R_detects_placeholder_literal(self, tmp_path):
        """R: 'placeholder' 한 줄 → 감지."""
        f = tmp_path / "test-watchdog.ps1"
        f.write_text("# Normal line\nplaceholder\n# Another line\n")
        hits = check_file(f)
        assert len(hits) == 1
        assert "placeholder" in hits[0][1]

    def test_R_detects_todo_colon(self, tmp_path):
        """R: 'TODO:' 패턴 → 감지."""
        f = tmp_path / "test-watchdog.ps1"
        f.write_text("$x = 1\n# TODO: 나중에 구현\n$y = 2\n")
        hits = check_file(f)
        assert len(hits) == 1
        assert "TODO:" in hits[0][1]

    def test_R_detects_hash_placeholder_comment(self, tmp_path):
        """R: '# placeholder' 주석 → 감지."""
        f = tmp_path / "test-watchdog.ps1"
        f.write_text("Start-Process 'cmd'\n# placeholder comment\n")
        hits = check_file(f)
        assert len(hits) == 1

    def test_R_normal_file_returns_empty(self, tmp_path):
        """R: 정상 watchdog 스크립트 → 빈 결과."""
        f = tmp_path / "normal-watchdog.ps1"
        f.write_text("# Claude Worker Watchdog\n$interval = 10\nwhile ($true) {\n    Start-Sleep $interval\n}\n")
        hits = check_file(f)
        assert hits == []

    def test_B_empty_file_returns_empty(self, tmp_path):
        """B: 빈 파일 → 빈 결과."""
        f = tmp_path / "empty-watchdog.ps1"
        f.write_text("")
        hits = check_file(f)
        assert hits == []


class TestMain:
    def test_R_detects_placeholder_exits_1(self, tmp_path):
        """R: placeholder 포함 디렉토리 → exit 1."""
        f = tmp_path / "bad-watchdog.ps1"
        f.write_text("# TODO: 구현 필요\n")
        result = main(["--scripts-dir", str(tmp_path)])
        assert result == 1

    def test_R_clean_directory_exits_0(self, tmp_path):
        """R: 정상 파일만 있는 디렉토리 → exit 0."""
        f = tmp_path / "good-watchdog.ps1"
        f.write_text("# Good script\n$x = 1\n")
        result = main(["--scripts-dir", str(tmp_path)])
        assert result == 0

    def test_E_no_watchdog_files_exits_0(self, tmp_path):
        """E: watchdog 파일 없는 디렉토리 → exit 0 (경고만)."""
        (tmp_path / "other.ps1").write_text("# Not a watchdog\n")
        result = main(["--scripts-dir", str(tmp_path)])
        assert result == 0
