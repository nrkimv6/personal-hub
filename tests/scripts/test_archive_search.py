"""
tests/scripts/test_archive_search.py — archive_search.py TC (T1-T3)

Phase T1: 단위 TC
Phase T3: 재현/통합 TC (실제 파일/unreachable host)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# scripts/ 경로를 sys.path에 추가
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_PATH = REPO_ROOT / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

# archive_search 임포트
import archive_search as m  # noqa: E402


# ---------- Phase T1: 단위 TC ----------

class TestSearchViaApi:

    def test_search_via_api_right(self, monkeypatch):
        """R: 정상 응답 → 파싱된 list[dict] 반환."""
        api_response = [
            {"title": "Watchdog Fix", "summary": "heartbeat fix", "tags": ["watchdog"], "file_path": "docs/archive/2026-04-10_watchdog.md", "archived_at": "2026-04-10"},
            {"title": "Pipeline Refactor", "summary": "pipeline cleanup", "tags": ["pipeline"], "file_path": "docs/archive/2026-04-11_pipeline.md", "archived_at": "2026-04-11"},
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = api_response

        monkeypatch.setattr(m.requests, "get", lambda *a, **kw: mock_resp)

        rows = m.search_via_api(q="watchdog", tags=None, date_from=None, date_to=None, deep=False, limit=20)
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert rows[0]["title"] == "Watchdog Fix"

    def test_search_via_api_paginated_response(self, monkeypatch):
        """R: {"items": [...], "total": N} 래퍼 형태도 지원."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"items": [
            {"title": "Item", "tags": ["infra"], "file_path": "docs/archive/x.md", "archived_at": "2026-01-01"}
        ], "total": 1}

        monkeypatch.setattr(m.requests, "get", lambda *a, **kw: mock_resp)

        rows = m.search_via_api(q="item", tags=None, date_from=None, date_to=None, deep=False, limit=20)
        assert len(rows) == 1

    def test_search_via_api_error_connection(self, capsys, monkeypatch):
        """E: ConnectionError → sys.exit(2) + stderr 복구 힌트."""
        import requests.exceptions as req_exc

        def mock_get(*args, **kwargs):
            raise req_exc.ConnectionError("Connection refused")

        monkeypatch.setattr(m.requests, "get", mock_get)

        with pytest.raises(SystemExit) as exc_info:
            m.main(["--q", "watchdog"])

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "API 응답 없음" in captured.err
        assert "복구 힌트" in captured.err
        assert "offline" in captured.err

    def test_search_via_api_error_5xx(self, capsys, monkeypatch):
        """E: 500 응답 → exit(2) + silent grep fallback 없음."""
        import requests as req_lib
        import requests.exceptions as req_exc

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_exc.HTTPError("500 Server Error")
        mock_resp.status_code = 500

        def mock_get(*args, **kwargs):
            return mock_resp

        monkeypatch.setattr(m.requests, "get", mock_get)

        # search_offline이 호출되지 않음을 검증
        called_offline = []
        original_search_offline = m.search_offline
        def mock_offline(*args, **kwargs):
            called_offline.append(True)
            return original_search_offline(*args, **kwargs)

        monkeypatch.setattr(m, "search_offline", mock_offline)

        with pytest.raises(SystemExit) as exc_info:
            m.main(["--q", "watchdog"])

        assert exc_info.value.code == 2
        assert len(called_offline) == 0, "silent fallback이 발생해서는 안 됨"
        captured = capsys.readouterr()
        assert "API 응답 없음" in captured.err


class TestSearchOffline:

    def _make_archive_file(self, tmp_path: Path, filename: str, content: str) -> Path:
        p = tmp_path / filename
        p.write_text(content, encoding="utf-8")
        return p

    def test_search_offline_right(self, tmp_path):
        """R: 실제 archive 샘플 3건 중 키워드 매칭 건만 반환."""
        self._make_archive_file(tmp_path, "2026-04-10_fix-watchdog-heartbeat.md",
                                "# Watchdog Fix\n\nwatchdog heartbeat 수정\n")
        self._make_archive_file(tmp_path, "2026-04-11_refactor-pipeline.md",
                                "# Pipeline Refactor\n\npipeline 리팩토링\n")
        self._make_archive_file(tmp_path, "2026-04-12_fix-watchdog-crash.md",
                                "# Watchdog Crash Fix\n\nwatchdog 크래시 수정\n")

        rows = m.search_offline(q="watchdog", tags=None, date_from=None, date_to=None, deep=False, archive_dir=tmp_path)
        assert len(rows) == 2
        paths = [r["file_path"] for r in rows]
        assert any("watchdog" in p for p in paths)
        # pipeline 파일은 포함 안 됨
        assert not any("pipeline" in p for p in paths)

    def test_search_offline_deep_content(self, tmp_path):
        """R: body에만 키워드 있는 파일도 deep=True 시 매칭.

        shallow 모드는 파일명+제목+본문 앞 100자만 검색.
        키워드를 100자 이후 위치에 배치하여 shallow에서 안 잡히고 deep에서만 잡히게 함.
        """
        # 앞 100자 패딩을 두고 그 이후에 키워드 배치
        padding = "x" * 120  # 100자 이상 패딩
        self._make_archive_file(tmp_path, "2026-04-10_refactor-core.md",
                                f"# Core Refactor\n\n{padding}\n\ndeep_keyword_xyz_unique 발견\n")
        self._make_archive_file(tmp_path, "2026-04-11_misc.md",
                                "# Misc\n\n일반 내용만 있음\n")

        rows_shallow = m.search_offline(q="deep_keyword_xyz_unique", tags=None, date_from=None, date_to=None, deep=False, archive_dir=tmp_path)
        rows_deep = m.search_offline(q="deep_keyword_xyz_unique", tags=None, date_from=None, date_to=None, deep=True, archive_dir=tmp_path)

        assert len(rows_shallow) == 0, "shallow 모드에서는 파일명/제목+본문 앞 100자만 검색 → 키워드 미매칭"
        assert len(rows_deep) == 1, "deep 모드에서는 본문 전체 검색 → 키워드 매칭"

    def test_search_offline_date_range_boundary(self, tmp_path):
        """B: date_from == 파일명 날짜 → 포함, date_to < 파일명 날짜 → 제외."""
        self._make_archive_file(tmp_path, "2026-04-10_watchdog.md", "# Watchdog\n\nwatchdog fix\n")
        self._make_archive_file(tmp_path, "2026-04-15_watchdog.md", "# Watchdog 2\n\nwatchdog v2\n")
        self._make_archive_file(tmp_path, "2026-04-20_watchdog.md", "# Watchdog 3\n\nwatchdog v3\n")

        # date_from=2026-04-10 → 2026-04-10 파일 포함
        rows_from = m.search_offline(q="watchdog", tags=None, date_from="2026-04-10", date_to=None, deep=False, archive_dir=tmp_path)
        assert len(rows_from) == 3  # 10, 15, 20 모두 포함

        # date_to=2026-04-14 → 2026-04-10만 포함, 15/20 제외
        rows_to = m.search_offline(q="watchdog", tags=None, date_from=None, date_to="2026-04-14", deep=False, archive_dir=tmp_path)
        assert len(rows_to) == 1
        assert "2026-04-10" in rows_to[0]["archived_at"]

    def test_search_offline_tags_filter(self, tmp_path):
        """R: 파일명 기반 태그 추출 후 --tags 교집합 매칭."""
        # watchdog 태그를 갖는 파일
        self._make_archive_file(tmp_path, "2026-04-10_fix-watchdog-heartbeat.md",
                                "# Watchdog Fix\n\nwatchdog fix\n")
        # pipeline 태그를 갖는 파일
        self._make_archive_file(tmp_path, "2026-04-11_refactor-pipeline-runner.md",
                                "# Pipeline\n\npipeline refactor\n")

        rows_watchdog = m.search_offline(q="", tags=["watchdog"], date_from=None, date_to=None, deep=False, archive_dir=tmp_path)
        # watchdog 파일만 반환됨
        paths = [r["file_path"] for r in rows_watchdog]
        assert all("watchdog" in p for p in paths)

    def test_search_offline_empty_dir(self, tmp_path):
        """B: 빈 디렉토리 → 빈 리스트 반환."""
        rows = m.search_offline(q="watchdog", tags=None, date_from=None, date_to=None, deep=False, archive_dir=tmp_path)
        assert rows == []


class TestRender:

    def test_render_text_right(self):
        """R: 동일 입력에 대해 비어있지 않은 테이블 반환."""
        rows = [
            {"title": "Watchdog Fix", "summary": "heartbeat fix", "tags": ["watchdog"], "file_path": "docs/archive/2026-04-10_watchdog.md", "archived_at": "2026-04-10"},
        ]
        result = m.render_text(rows)
        assert isinstance(result, str)
        assert "| date | tags | title | one-liner |" in result
        assert "2026-04-10" in result
        assert "Watchdog Fix" in result
        assert "path:" in result  # path는 별도 행으로

    def test_render_text_empty(self):
        """B: 빈 리스트 → "(검색 결과 없음)" 반환."""
        result = m.render_text([])
        assert "없음" in result

    def test_render_json_right(self):
        """R: 동일 입력에 대해 JSON 역파싱 가능."""
        rows = [
            {"title": "Test", "summary": "test summary", "tags": ["test"], "file_path": "docs/archive/test.md", "archived_at": "2026-01-01"},
        ]
        result = m.render_json(rows)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert parsed[0]["title"] == "Test"

    def test_render_json_empty(self):
        """B: 빈 리스트 → 빈 JSON 배열."""
        result = m.render_json([])
        parsed = json.loads(result)
        assert parsed == []


# ---------- Phase T3: 재현/통합 TC ----------

class TestT3Integration:

    def test_search_api_fallback_to_offline_is_blocked(self, capsys):
        """통합: unreachable host(localhost:9999) → silent fallback 없음 + exit(2).

        이 테스트는 silent drop 재발을 차단하는 핵심 회귀 테스트.
        실제 requests 라이브러리로 unreachable host 호출 → ConnectionError → exit(2).
        offline 모드로 자동 fallback이 발생하지 않음을 검증.
        """
        # archive_search의 API_BASE_URL을 unreachable host로 오버라이드
        original_url = m.API_BASE_URL

        called_offline = []
        original_offline = m.search_offline

        def track_offline(*args, **kwargs):
            called_offline.append(True)
            return original_offline(*args, **kwargs)

        try:
            m.API_BASE_URL = "http://localhost:9999"

            with patch.object(m, "search_offline", side_effect=track_offline):
                with pytest.raises(SystemExit) as exc_info:
                    m.main(["--q", "watchdog"])

            assert exc_info.value.code == 2, "unreachable host는 exit(2)여야 함"
            assert len(called_offline) == 0, "silent fallback이 발생해서는 안 됨"
            captured = capsys.readouterr()
            assert "API 응답 없음" in captured.err
            assert "offline" in captured.err  # 복구 힌트에 offline 방법 포함
        finally:
            m.API_BASE_URL = original_url

    def test_search_offline_against_real_archive_dir(self):
        """통합: 실제 archive 디렉토리에서 grep 동작 확인.

        archive_search.py의 ARCHIVE_DIR (메인 레포 기준 .worktrees/plans/docs/archive/)
        또는 메인 레포의 plans worktree에서 실제 파일로 테스트.
        worktree 환경에서 .worktrees/plans/가 없는 경우 skip.
        """
        # archive_search.py가 계산한 ARCHIVE_DIR 사용
        real_archive_dir = m.ARCHIVE_DIR
        if not real_archive_dir.exists():
            # 대안: 메인 레포 상위에서 찾기
            main_repo = REPO_ROOT.parent.parent  # .worktrees/ 위 → 레포 루트
            alt_dir = main_repo / ".worktrees" / "plans" / "docs" / "archive"
            if not alt_dir.exists():
                pytest.skip(f"실제 archive 디렉토리 없음 (worktree 환경): {real_archive_dir}")
            real_archive_dir = alt_dir

        md_files = list(real_archive_dir.glob("*.md"))
        if not md_files:
            pytest.skip("archive 디렉토리에 .md 파일 없음")

        # watchdog 관련 파일이 있는지 먼저 확인
        has_watchdog = any("watchdog" in f.name.lower() for f in md_files)
        if not has_watchdog:
            # watchdog 파일이 없으면 첫 번째 파일의 날짜로 검색
            first_file = sorted(md_files)[0]
            keyword = first_file.stem.split("-")[-1] if "-" in first_file.stem else "fix"
            rows = m.search_offline(q=keyword, tags=None, date_from=None, date_to=None, deep=False, archive_dir=real_archive_dir)
        else:
            rows = m.search_offline(q="watchdog", tags=None, date_from=None, date_to=None, deep=False, archive_dir=real_archive_dir)

        assert isinstance(rows, list)
        assert len(rows) > 0, "실제 archive에서 검색 결과가 있어야 함"
        # 결과 구조 검증
        for r in rows:
            assert "title" in r
            assert "file_path" in r
            assert "archived_at" in r
