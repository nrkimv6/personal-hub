"""
TextDiffDetector 단위 테스트
"""
import pytest
from unittest.mock import MagicMock, patch


def _make_image(color=(255, 255, 255)):
    try:
        from PIL import Image
        return Image.new("RGB", (100, 100), color=color)
    except ImportError:
        return MagicMock()


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    import sys
    for k in list(sys.modules.keys()):
        if "text_diff" in k or (k.startswith("app.modules.kakao_monitor") and "text_diff" in k):
            del sys.modules[k]
    yield


# ---------------------------------------------------------------------------
# detect_new_messages 테스트
# ---------------------------------------------------------------------------

def test_new_messages_right():
    """R: prev=[A,B], curr=[A,B,C,D] → [C,D]"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    result = d.detect_new_messages(["A", "B"], ["A", "B", "C", "D"])
    assert result == ["C", "D"]


def test_no_change():
    """B: 동일 리스트 → 빈 리스트"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    assert d.detect_new_messages(["A", "B"], ["A", "B"]) == []


def test_both_empty():
    """B: 빈 vs 빈 → 빈 리스트"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    assert d.detect_new_messages([], []) == []


def test_prev_empty():
    """B: prev=[], curr=[A,B] → [A,B] (첫 스캔)"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    result = d.detect_new_messages([], ["A", "B"])
    assert result == ["A", "B"]


def test_completely_different():
    """E: prev=[A,B], curr=[X,Y] → [X,Y]"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    result = d.detect_new_messages(["A", "B"], ["X", "Y"])
    assert "X" in result and "Y" in result


def test_messages_with_whitespace():
    """B: 공백/개행 포함 메시지 처리"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    result = d.detect_new_messages(["A"], ["A", "새 메시지  "])
    # 공백 포함 메시지도 새 메시지로 인식
    assert len(result) == 1


def test_whitespace_only_excluded():
    """B: 공백만 있는 라인은 필터링됨"""
    from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
    d = TextDiffDetector()
    result = d.detect_new_messages([], ["   ", "\t", "실제메시지"])
    assert "실제메시지" in result
    # 공백만인 항목은 제외
    assert "   " not in result


# ---------------------------------------------------------------------------
# has_visual_change 테스트
# ---------------------------------------------------------------------------

def test_visual_change_different_images():
    """R: 다른 이미지 → True"""
    import sys, types
    fake_imagehash = types.ModuleType("imagehash")
    h1, h2 = MagicMock(), MagicMock()
    h1.__sub__ = MagicMock(return_value=10)
    fake_imagehash.phash = MagicMock(side_effect=[h1, h2])

    with patch.dict(sys.modules, {"imagehash": fake_imagehash}):
        from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
        d = TextDiffDetector()
        img1 = _make_image((255, 0, 0))
        img2 = _make_image((0, 255, 0))
        assert d.has_visual_change(img1, img2, threshold=5) is True


def test_visual_change_same_image():
    """R: 동일 이미지 → False"""
    import sys, types
    fake_imagehash = types.ModuleType("imagehash")
    h1, h2 = MagicMock(), MagicMock()
    h1.__sub__ = MagicMock(return_value=0)
    fake_imagehash.phash = MagicMock(side_effect=[h1, h2])

    with patch.dict(sys.modules, {"imagehash": fake_imagehash}):
        from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
        d = TextDiffDetector()
        img = _make_image()
        assert d.has_visual_change(img, img, threshold=5) is False


def test_visual_change_threshold_boundary():
    """B: 해밍 거리 == threshold → False (경계값, 변경 아님)"""
    import sys, types
    fake_imagehash = types.ModuleType("imagehash")
    h1, h2 = MagicMock(), MagicMock()
    h1.__sub__ = MagicMock(return_value=5)
    fake_imagehash.phash = MagicMock(side_effect=[h1, h2])

    with patch.dict(sys.modules, {"imagehash": fake_imagehash}):
        from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
        d = TextDiffDetector()
        assert d.has_visual_change(_make_image(), _make_image(), threshold=5) is False


def test_visual_change_threshold_plus_one():
    """B: 해밍 거리 == threshold+1 → True"""
    import sys, types
    fake_imagehash = types.ModuleType("imagehash")
    h1, h2 = MagicMock(), MagicMock()
    h1.__sub__ = MagicMock(return_value=6)
    fake_imagehash.phash = MagicMock(side_effect=[h1, h2])

    with patch.dict(sys.modules, {"imagehash": fake_imagehash}):
        from app.modules.kakao_monitor.utils.text_diff import TextDiffDetector
        d = TextDiffDetector()
        assert d.has_visual_change(_make_image(), _make_image(), threshold=5) is True
