"""
OCR 엔진 래퍼 — PaddleOCR 1순위, Windows OCR fallback.

Usage:
    engine = get_ocr_engine()
    blocks = engine.recognize(pil_image)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 의존성 lazy import
# ---------------------------------------------------------------------------
try:
    from paddleocr import PaddleOCR as _PaddleOCR  # type: ignore
    _PADDLE_AVAILABLE = True
except ImportError:
    _PADDLE_AVAILABLE = False

try:
    import windows_ocr as _windows_ocr  # type: ignore
    _WINDOWS_OCR_AVAILABLE = True
except ImportError:
    _WINDOWS_OCR_AVAILABLE = False

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None  # type: ignore


@dataclass
class TextBlock:
    """OCR로 인식된 텍스트 블록."""
    text: str
    bbox: tuple  # (x1, y1, x2, y2) 또는 PaddleOCR 형식의 4점 좌표
    confidence: float = 1.0
    extra: dict = field(default_factory=dict)


class KakaoOCREngine:
    """PaddleOCR (1순위) + Windows OCR (fallback) 래퍼."""

    def __init__(self) -> None:
        self._paddle: object | None = None
        self._use_windows_ocr: bool = False
        self._init_engine()

    def _init_engine(self) -> None:
        if _PADDLE_AVAILABLE:
            try:
                logger.info("PaddleOCR 로드 중 (첫 실행 시 모델 다운로드 발생)...")
                self._paddle = _PaddleOCR(
                    use_angle_cls=True,
                    lang="korean",
                    use_gpu=False,
                    show_log=False,
                )
                logger.info("PaddleOCR 로드 완료")
                return
            except Exception as exc:
                logger.warning("PaddleOCR 초기화 실패: %s — Windows OCR fallback 사용", exc)

        if _WINDOWS_OCR_AVAILABLE:
            self._use_windows_ocr = True
            logger.info("Windows OCR 사용")
        else:
            logger.error(
                "OCR 엔진 없음. paddleocr 또는 windows-ocr 중 하나를 설치하세요."
            )

    def recognize(self, image: object) -> list[TextBlock]:
        """PIL Image → TextBlock 리스트.

        Args:
            image: PIL.Image.Image

        Returns:
            인식된 텍스트 블록 목록 (신뢰도 순 정렬)
        """
        if image is None:
            return []

        if self._paddle is not None:
            return self._recognize_paddle(image)
        if self._use_windows_ocr:
            return self._recognize_windows(image)

        logger.warning("사용 가능한 OCR 엔진 없음")
        return []

    # ------------------------------------------------------------------ #
    # PaddleOCR
    # ------------------------------------------------------------------ #

    def _recognize_paddle(self, image: object) -> list[TextBlock]:
        try:
            results = self._paddle.ocr(image, cls=True)  # type: ignore[union-attr]
            blocks: list[TextBlock] = []
            if not results or results[0] is None:
                return blocks
            for line in results[0]:
                # line = [[pt1, pt2, pt3, pt4], (text, confidence)]
                bbox_pts, (text, conf) = line
                # bbox_pts: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                xs = [p[0] for p in bbox_pts]
                ys = [p[1] for p in bbox_pts]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                blocks.append(TextBlock(text=text, bbox=bbox, confidence=float(conf)))
            return sorted(blocks, key=lambda b: b.bbox[1])  # y 좌표 오름차순
        except Exception as exc:
            logger.exception("PaddleOCR 인식 오류: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Windows OCR
    # ------------------------------------------------------------------ #

    def _recognize_windows(self, image: object) -> list[TextBlock]:
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                _windows_ocr.recognize_pil_image(image, language="ko")  # type: ignore
            )
            loop.close()

            blocks: list[TextBlock] = []
            for line in result.lines:
                text = " ".join(w.text for w in line.words)
                # Windows OCR bounding box
                r = line.bounding_rect
                bbox = (r.x, r.y, r.x + r.width, r.y + r.height)
                blocks.append(TextBlock(text=text, bbox=bbox, confidence=1.0))
            return blocks
        except Exception as exc:
            logger.exception("Windows OCR 인식 오류: %s", exc)
            return []

    def get_text_lines(self, image: object) -> list[str]:
        """recognize() 결과에서 텍스트 라인만 추출."""
        return [b.text for b in self.recognize(image) if b.text.strip()]


# ---------------------------------------------------------------------------
# 모듈 레벨 싱글톤
# ---------------------------------------------------------------------------
_engine_instance: KakaoOCREngine | None = None


def get_ocr_engine() -> KakaoOCREngine:
    """모듈 레벨 KakaoOCREngine 싱글톤 반환."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = KakaoOCREngine()
    return _engine_instance
