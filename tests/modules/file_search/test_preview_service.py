"""
file-search preview service 테스트

SearchService.get_file_preview()의 파일 검증, 크기 제한, 디코딩 fallback을 고정합니다.
"""

from pathlib import Path

import pytest

from app.modules.file_search.services.search_service import (
    FilePreviewError,
    MAX_PREVIEW_BYTES,
    SearchService,
)


def test_get_file_preview_right_returns_text_payload(tmp_path: Path):
    service = SearchService()

    target = tmp_path / "hello.md"
    target.write_text("# Title\nHello\n", encoding="utf-8")

    preview = service.get_file_preview(str(target))

    assert preview.file_path == str(target)
    assert preview.file_name == "hello.md"
    assert preview.extension == "md"
    assert preview.size_bytes == target.stat().st_size
    assert preview.encoding in ("utf-8-sig", "utf-8")
    assert preview.content.startswith("# Title")


def test_get_file_preview_boundary_rejects_oversized_text(tmp_path: Path):
    service = SearchService()

    target = tmp_path / "big.txt"
    target.write_bytes(b"a" * (MAX_PREVIEW_BYTES + 1))

    with pytest.raises(FilePreviewError) as exc:
        service.get_file_preview(str(target))

    assert exc.value.status_code == 413


def test_get_file_preview_error_rejects_unsupported_extension(tmp_path: Path):
    service = SearchService()

    target = tmp_path / "data.bin"
    target.write_text("hello", encoding="utf-8")

    with pytest.raises(FilePreviewError) as exc:
        service.get_file_preview(str(target))

    assert exc.value.status_code == 415


def test_get_file_preview_error_rejects_directory_path(tmp_path: Path):
    service = SearchService()

    with pytest.raises(FilePreviewError) as exc:
        service.get_file_preview(str(tmp_path))

    assert exc.value.status_code == 404


def test_get_file_preview_correct_cp949_fallback(tmp_path: Path):
    service = SearchService()

    target = tmp_path / "korean.txt"
    target.write_bytes("한글".encode("cp949"))

    preview = service.get_file_preview(str(target))

    assert preview.encoding == "cp949"
    assert preview.content == "한글"
