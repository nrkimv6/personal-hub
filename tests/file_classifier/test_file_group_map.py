"""
FILE_GROUP_MAP CORRECT TC
- Conformance: 확장자 형식 검증
- Ordering: 중복 없음
- Range: 지원 종수 검증
- Existence: 특정 확장자 매핑 확인
- Cardinality: 그룹별 확장자 수 검증
"""
import pytest
from app.modules.file_classifier.workers.scanner import _GROUP_EXTENSIONS, FILE_GROUP_MAP, get_file_group

class TestFileGroupMapConformance:
    """C-Conformance: 모든 확장자가 소문자 . 시작인지"""
    def test_all_extensions_lowercase(self):
        for group, exts in _GROUP_EXTENSIONS.items():
            for ext in exts:
                assert ext == ext.lower(), f"{group}/{ext} 는 소문자여야 함"

    def test_all_extensions_start_with_dot(self):
        for group, exts in _GROUP_EXTENSIONS.items():
            for ext in exts:
                assert ext.startswith("."), f"{group}/{ext} 는 .으로 시작해야 함"

class TestFileGroupMapOrdering:
    """C-Ordering: 중복 등록 없음"""
    def test_no_duplicate_extensions(self):
        all_exts = []
        for exts in _GROUP_EXTENSIONS.values():
            all_exts.extend(exts)
        assert len(all_exts) == len(set(all_exts)), "중복 확장자 존재"

    def test_reverse_map_consistent(self):
        for ext, group in FILE_GROUP_MAP.items():
            assert ext in _GROUP_EXTENSIONS.get(group, set()), f"{ext} 역방향 매핑 불일치"

class TestFileGroupMapExistence:
    """C-Existence: 특정 확장자 반드시 존재"""
    @pytest.mark.parametrize("ext,expected_group", [
        (".apk", "installer"),
        (".vsix", "installer"),
        (".appx", "installer"),
        (".ipa", "installer"),
        (".hwpx", "document"),
        (".ics", "document"),
        (".html", "document"),
        (".mp4", "video"),
        (".mkv", "video"),
        (".jpg", "image"),
        (".png", "image"),
        (".psd", "image"),
        (".svg", "image"),
        (".mid", "music"),
        (".dtx", "game"),
        (".torrent", "misc"),  # misc에 없으면 get_file_group → "misc"
    ])
    def test_extension_mapping(self, ext, expected_group):
        result = get_file_group(ext)
        assert result == expected_group, f"{ext} → 기대:{expected_group}, 실제:{result}"

class TestFileGroupMapCardinality:
    """C-Cardinality: 그룹별 최소 확장자 수"""
    @pytest.mark.parametrize("group,min_count", [
        ("music", 9),
        ("video", 8),
        ("image", 10),
        ("archive", 6),
        ("document", 10),
        ("installer", 8),
        ("game", 6),
    ])
    def test_group_min_extension_count(self, group, min_count):
        count = len(_GROUP_EXTENSIONS.get(group, set()))
        assert count >= min_count, f"{group} 확장자 수 {count} < 최소 {min_count}"

class TestFileGroupMapRange:
    """C-Range: 경계값 처리"""
    def test_unknown_extension_returns_misc(self):
        assert get_file_group(".xyz123") == "misc"
        assert get_file_group(".unknown") == "misc"

    def test_empty_extension_returns_misc(self):
        assert get_file_group("") == "misc"

    def test_case_insensitive(self):
        assert get_file_group(".MP3") == "music"
        assert get_file_group(".Mp3") == "music"
        assert get_file_group(".ZIP") == "archive"
        assert get_file_group(".PDF") == "document"
