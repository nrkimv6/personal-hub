"""
KakaoOCREngine 단위 테스트
"""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _make_blank_image(width=100, height=100):
    try:
        from PIL import Image
        return Image.new("RGB", (width, height), color=(255, 255, 255))
    except ImportError:
        return MagicMock()


def _make_paddle_result(text="안녕하세요", conf=0.95):
    """PaddleOCR 결과 형식 반환."""
    bbox = [[10, 10], [90, 10], [90, 30], [10, 30]]
    return [[[bbox, (text, conf)]]]


@pytest.fixture(autouse=True)
def clear_ocr_cache():
    for key in list(sys.modules.keys()):
        if "ocr_engine" in key or "kakao_monitor" in key:
            del sys.modules[key]
    yield


def test_recognize_right():
    """R: 한글 포함 이미지 → TextBlock 리스트 반환."""
    fake_paddle_cls = MagicMock()
    fake_paddle_instance = MagicMock()
    fake_paddle_instance.ocr = MagicMock(return_value=_make_paddle_result("안녕하세요"))
    fake_paddle_cls.return_value = fake_paddle_instance

    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = fake_paddle_cls

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine, TextBlock
        engine = KakaoOCREngine()
        image = _make_blank_image()
        blocks = engine.recognize(image)

    assert len(blocks) == 1
    assert blocks[0].text == "안녕하세요"
    assert isinstance(blocks[0], TextBlock)
    assert 0.0 <= blocks[0].confidence <= 1.0


def test_recognize_empty_image():
    """B: None 입력 → 빈 리스트."""
    fake_paddle_cls = MagicMock()
    fake_paddle_instance = MagicMock()
    fake_paddle_instance.ocr = MagicMock(return_value=[[]])
    fake_paddle_cls.return_value = fake_paddle_instance

    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = fake_paddle_cls

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine
        engine = KakaoOCREngine()
        blocks = engine.recognize(None)

    assert blocks == []


def test_recognize_tiny_image():
    """B: 1x1 이미지 → 빈 리스트 (결과 없음)."""
    fake_paddle_cls = MagicMock()
    fake_paddle_instance = MagicMock()
    fake_paddle_instance.ocr = MagicMock(return_value=[None])
    fake_paddle_cls.return_value = fake_paddle_instance

    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = fake_paddle_cls

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine
        engine = KakaoOCREngine()
        image = _make_blank_image(1, 1)
        blocks = engine.recognize(image)

    assert blocks == []


def test_recognize_large_image():
    """B: 4000x3000 이미지 → 정상 처리."""
    fake_paddle_cls = MagicMock()
    fake_paddle_instance = MagicMock()
    fake_paddle_instance.ocr = MagicMock(return_value=_make_paddle_result("텍스트"))
    fake_paddle_cls.return_value = fake_paddle_instance

    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = fake_paddle_cls

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine
        engine = KakaoOCREngine()
        image = _make_blank_image(4000, 3000)
        blocks = engine.recognize(image)

    assert len(blocks) >= 1


def test_fallback_to_windows_ocr():
    """E: PaddleOCR import 실패 시 Windows OCR fallback."""
    # PaddleOCR를 import 오류로 만들기
    class _ImportError:
        def __init__(self, *a, **kw):
            raise ImportError("no paddle")

    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = _ImportError

    fake_windows_ocr = types.ModuleType("windows_ocr")

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod, "windows_ocr": fake_windows_ocr}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine
        engine = KakaoOCREngine()

    assert engine._use_windows_ocr is True


def test_both_engines_unavailable():
    """E: PaddleOCR + Windows OCR 모두 실패 시 빈 리스트."""
    fake_paddle_mod = MagicMock()
    fake_paddle_mod.PaddleOCR = MagicMock(side_effect=ImportError)

    with patch.dict(sys.modules, {"paddleocr": None, "windows_ocr": None}):
        from app.modules.kakao_monitor.utils.ocr_engine import KakaoOCREngine
        engine = KakaoOCREngine()
        blocks = engine.recognize(_make_blank_image())

    assert blocks == []


def test_singleton_instance():
    """Re: get_ocr_engine() 두 번 호출 시 동일 인스턴스 반환."""
    fake_paddle_mod = types.ModuleType("paddleocr")
    fake_paddle_mod.PaddleOCR = MagicMock()

    with patch.dict(sys.modules, {"paddleocr": fake_paddle_mod}):
        from app.modules.kakao_monitor.utils.ocr_engine import get_ocr_engine
        e1 = get_ocr_engine()
        e2 = get_ocr_engine()

    assert e1 is e2
