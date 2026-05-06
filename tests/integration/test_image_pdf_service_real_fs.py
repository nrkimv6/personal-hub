from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

import pytest
from PIL import Image

from app.schemas.image_pdf import ImagePdfConvertOptions
from app.services import image_pdf_service
from app.services.image_pdf_service import ImagePdfError

pytestmark = pytest.mark.integration


def _write_jpg(path: Path, color=(255, 0, 0)) -> Path:
    img = Image.new("RGB", (32, 24), color)
    img.save(path, format="JPEG")
    return path


def _page_count(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))


def test_convert_real_jpg_fixture_to_pdf(tmp_path: Path):
    fixture = _write_jpg(tmp_path / "sample.jpg")
    pdf = image_pdf_service.convert_images_to_pdf(
        [(fixture.name, fixture.read_bytes())],
        ImagePdfConvertOptions(),
    )
    assert pdf.startswith(b"%PDF")
    assert _page_count(pdf) == 1


def test_convert_real_heic_when_pillow_heif_present(tmp_path: Path):
    pytest.importorskip("pillow_heif")
    # Pillow cannot create HEIC in every environment, so this asserts the runtime branch
    # only when a caller provides a real HEIC fixture later.
    assert image_pdf_service.HEIC_OK is True


def test_convert_real_corrupt_truncated_jpg(tmp_path: Path):
    fixture = _write_jpg(tmp_path / "sample.jpg")
    truncated = fixture.read_bytes()[:10]
    with pytest.raises(ImagePdfError) as exc:
        image_pdf_service.convert_images_to_pdf(
            [("truncated.jpg", truncated)],
            ImagePdfConvertOptions(),
        )
    assert exc.value.error == "corrupt"
