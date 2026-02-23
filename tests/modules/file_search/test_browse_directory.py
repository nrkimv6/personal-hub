"""browse_directory 경로 처리 테스트

Windows 드라이브 루트 경로 보정 및 parent 경로 로직을 검증합니다.
"""
import os

import pytest

from app.modules.file_search.services.search_service import SearchService


@pytest.fixture
def service():
    return SearchService()


class TestDriveRootPathCorrection:
    """드라이브 루트 경로 보정 테스트 (Windows 전용)."""

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_drive_root_path_preserved(self, service):
        """D:\\ 입력 시 current가 D:\\ 그대로 반환."""
        resp = service.browse_directory("D:\\")
        assert resp.current == "D:\\"

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_drive_letter_without_backslash(self, service):
        """D: 입력 시 D:\\로 보정되어 반환."""
        resp = service.browse_directory("D:")
        assert resp.current == "D:\\"

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_drive_root_parent_is_none(self, service):
        """드라이브 루트에서 parent는 None (드라이브 목록으로 돌아감)."""
        resp = service.browse_directory("D:\\")
        assert resp.parent is None

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_subdirectory_parent_not_none(self, service):
        """하위 디렉토리에서 parent는 상위 경로."""
        resp = service.browse_directory("D:\\work")
        assert resp.parent == "D:\\"

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_empty_path_returns_drives(self, service):
        """빈 경로 입력 시 드라이브 목록 반환."""
        resp = service.browse_directory("")
        assert resp.current == ""
        assert resp.directories is not None
        assert len(resp.directories) > 0

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")
    def test_rstrip_trailing_slashes(self, service):
        """일반 경로의 trailing slash는 정상 제거."""
        resp = service.browse_directory("D:\\work\\")
        assert resp.current == "D:\\work"
